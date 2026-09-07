from datetime import datetime, timedelta
from hashlib import sha1
from zoneinfo import ZoneInfo

import frappe

from biometric_integration.biometric_integration.hikvision import (
    DEFAULT_DUPLICATE_SECONDS,
    DEFAULT_TIMEZONE,
    _event_key,
    _fetch_events,
    _get_enabled_devices,
    _group_events,
    _parse_event_time,
    _settings,
)

MOVEMENT_DOCTYPE = "Daily Employee Movement Log"
MOVEMENT_ENTRY_DOCTYPE = "Daily Employee Movement Entry"


def _as_local_naive(event_dt, timezone_name):
    return event_dt.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)


def _day_from_event(event_dt, timezone_name):
    return event_dt.astimezone(ZoneInfo(timezone_name)).date()


def _stable_name(employee, log_date):
    digest = sha1(f"{employee}|{log_date}".encode()).hexdigest()[:16]
    return f"MOV-{digest}"


def _stable_session_key(employee, log_date, first_event_key):
    digest = sha1(f"{employee}|{log_date}|{first_event_key}".encode()).hexdigest()[:24]
    return f"HIKSESSION-{digest}"


def _event_value(event, *names):
    for name in names:
        value = event.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _get_or_create_daily_log(employee, log_date):
    name = _stable_name(employee, log_date)
    if frappe.db.exists(MOVEMENT_DOCTYPE, name):
        return frappe.get_doc(MOVEMENT_DOCTYPE, name)

    doc = frappe.new_doc(MOVEMENT_DOCTYPE)
    doc.name = name
    doc.employee = employee
    doc.log_date = log_date
    doc.employee_name = frappe.db.get_value("Employee", employee, "employee_name") or ""
    doc.insert(ignore_permissions=True)
    return doc


def _event_exists(event_key):
    return frappe.db.exists(MOVEMENT_ENTRY_DOCTYPE, {"event_key": event_key})


def _append_event(log, device, event):
    """Append one event only if it does not already exist anywhere."""
    event_key = event["event_key"]

    if _event_exists(event_key):
        return False

    timezone_name = device.timezone or DEFAULT_TIMEZONE
    row = log.append("movement_entries", {})
    row.event_time = _as_local_naive(event["event_dt"], timezone_name)
    row.device_name = device.device_name or device.ip
    row.device_serial_number = device.serial_number or device.device_id or device.ip
    row.employee_device_id = _event_value(event, "employeeNoString")
    row.authentication_mode = _event_value(
        event,
        "currentVerifyMode",
        "currentVerifyModeName",
        "authenticationMode",
        "verifyMode",
    )
    row.authentication_result = _event_value(
        event,
        "currentEvent",
        "authenticationResult",
        "result",
    )
    row.card_no = _event_value(event, "cardNo", "cardNumber")
    row.direction = "LOG"
    row.event_key = event_key
    return True


def _save_new_movement_event(log, device, event):
    """Save a new event safely; never save a log merely because an old event was seen."""
    if _event_exists(event["event_key"]):
        return False

    before = len(log.movement_entries or [])
    if not _append_event(log, device, event):
        return False

    if len(log.movement_entries or []) <= before:
        return False

    try:
        log.save(ignore_permissions=True)
        return True
    except frappe.DuplicateEntryError:
        # A concurrent worker may have inserted the same unique event key.
        # The unique DB constraint remains the final protection.
        frappe.logger().warning(
            "Duplicate Hikvision movement event skipped: %s",
            event["event_key"],
        )
        return False


def _load_events_for_log(log):
    return frappe.get_all(
        MOVEMENT_ENTRY_DOCTYPE,
        filters={"parent": log.name, "parenttype": MOVEMENT_DOCTYPE},
        fields=[
            "name",
            "parent",
            "event_time",
            "device_name",
            "device_serial_number",
            "employee_device_id",
            "authentication_mode",
            "authentication_result",
            "card_no",
            "direction",
            "event_key",
            "session_key",
            "employee_checkin",
        ],
        order_by="event_time asc, idx asc",
        limit_page_length=0,
    )


def _device_identity(row):
    return row.get("device_serial_number") or row.get("device_name") or "UNKNOWN"


def _sessionize(rows):
    """Create sessions from consecutive events on the same physical device.

    Rows belong to one employee/day movement log, so employee identity is already
    fixed. A change of physical device starts a new session. Thus Office -> Factory
    -> Office produces three sessions, while repeated events on one device stay in
    one session.
    """
    sessions = []
    current = None

    for row in rows:
        identity = _device_identity(row)
        if current is None or identity != current["device_identity"]:
            current = {"device_identity": identity, "rows": []}
            sessions.append(current)
        current["rows"].append(row)

    return sessions


def _find_checkin_by_session(session_key):
    return frappe.db.get_value(
        "Employee Checkin",
        {"biometric_session_key": session_key},
        ["name", "time", "log_type", "device_id", "biometric_event_key"],
        as_dict=True,
    )


def _get_device_for_row(row):
    settings = _settings()
    row_serial = (row.device_serial_number or "").strip()
    row_name = (row.device_name or "").strip()

    for device in settings.devices or []:
        device_serial = (
            device.serial_number or device.device_id or device.ip or ""
        ).strip()
        device_name = (device.device_name or "").strip()

        if row_serial and row_serial == device_serial:
            return device
        if row_name and row_name == device_name:
            return device

    return None


def _create_or_update_checkin(employee, row, log_type, session_key):
    meta = frappe.get_meta("Employee Checkin")
    if not meta.has_field("biometric_session_key"):
        raise RuntimeError(
            "Employee Checkin biometric_session_key is missing. Run bench migrate."
        )

    device = _get_device_for_row(row)
    latitude = device.latitude if device and device.latitude is not None else None
    longitude = device.longitude if device and device.longitude is not None else None

    if latitude is None or longitude is None:
        raise RuntimeError(
            f"Latitude and longitude are required for biometric check-in. "
            f"Device '{row.device_name}' ({row.device_serial_number}) has no configured coordinates."
        )

    full_session_key = f"{session_key}:{log_type}"
    existing = _find_checkin_by_session(full_session_key)

    if existing:
        checkin = frappe.get_doc("Employee Checkin", existing.name)
        changed = False

        values = {
            "time": row.event_time,
            "log_type": log_type,
            "device_id": row.device_serial_number or row.device_name,
            "latitude": latitude,
            "longitude": longitude,
        }
        for fieldname, value in values.items():
            if getattr(checkin, fieldname, None) != value:
                setattr(checkin, fieldname, value)
                changed = True

        if meta.has_field("biometric_event_key") and checkin.biometric_event_key != row.event_key:
            checkin.biometric_event_key = row.event_key
            changed = True

        if meta.has_field("biometric_movement_log") and checkin.biometric_movement_log != row.parent:
            checkin.biometric_movement_log = row.parent
            changed = True

        if changed:
            checkin.save(ignore_permissions=True)
        return checkin.name

    checkin = frappe.new_doc("Employee Checkin")
    checkin.employee = employee
    checkin.time = row.event_time
    checkin.log_type = log_type
    checkin.device_id = row.device_serial_number or row.device_name
    checkin.latitude = latitude
    checkin.longitude = longitude
    checkin.biometric_session_key = full_session_key

    if meta.has_field("biometric_event_key"):
        checkin.biometric_event_key = row.event_key
    if meta.has_field("biometric_movement_log"):
        checkin.biometric_movement_log = row.parent

    checkin.insert(ignore_permissions=True)
    return checkin.name


def _reconcile_daily_log(log):
    rows = _load_events_for_log(log)
    if not rows:
        return {"sessions": 0, "checkins": 0}

    sessions = _sessionize(rows)
    checkins = 0

    for session in sessions:
        first = session["rows"][0]
        last = session["rows"][-1]
        session_key = _stable_session_key(log.employee, log.log_date, first.event_key)

        for index, row in enumerate(session["rows"]):
            direction = "LOG"
            if index == 0:
                direction = "IN"
            elif index == len(session["rows"]) - 1:
                direction = "OUT"

            frappe.db.set_value(
                MOVEMENT_ENTRY_DOCTYPE,
                row.name,
                {"direction": direction, "session_key": session_key},
                update_modified=False,
            )

        in_checkin = _create_or_update_checkin(log.employee, first, "IN", session_key)
        checkins += 1

        out_checkin = None
        if len(session["rows"]) > 1:
            out_checkin = _create_or_update_checkin(log.employee, last, "OUT", session_key)
            checkins += 1

        for row in session["rows"]:
            checkin_name = None
            if row.name == first.name:
                checkin_name = in_checkin
            elif row.name == last.name and out_checkin:
                checkin_name = out_checkin

            frappe.db.set_value(
                MOVEMENT_ENTRY_DOCTYPE,
                row.name,
                "employee_checkin",
                checkin_name,
                update_modified=False,
            )

    return {"sessions": len(sessions), "checkins": checkins}


def _normalize_device_events(device, raw_events, duplicate_seconds):
    timezone_name = device.timezone or DEFAULT_TIMEZONE
    normalized = []

    for raw in raw_events:
        if int(raw.get("major") or 0) != 5 or int(raw.get("minor") or 0) != 75:
            continue

        event_dt = _parse_event_time(raw.get("time"), timezone_name)
        employee_no = str(raw.get("employeeNoString") or "").strip()
        if not event_dt or not employee_no:
            continue

        employee = frappe.db.get_value(
            "Employee",
            {"attendance_device_id": employee_no, "status": "Active"},
            "name",
        )
        if not employee:
            continue

        normalized.append({
            **raw,
            "event_dt": event_dt,
            "employee": employee,
            "event_key": _event_key(device, raw),
            "device_serial": device.serial_number or device.device_id or device.ip,
        })

    return _group_events(normalized, duplicate_seconds)


def _scheduler_start(to_datetime):
    local_now = to_datetime.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)


def sync_all_devices(from_datetime=None, to_datetime=None, require_scheduler=False):
    settings = _settings()

    if not settings.enabled:
        return {"status": "error", "message": "Biometric Integration is disabled.", "devices": []}

    if require_scheduler and not settings.scheduler_enabled:
        return {"status": "skipped", "message": "Scheduler is disabled.", "devices": []}

    if from_datetime is None or to_datetime is None:
        to_datetime = frappe.utils.now_datetime()
        from_datetime = _scheduler_start(to_datetime)

    devices = _get_enabled_devices()
    if not devices:
        return {"status": "error", "message": "No enabled Hikvision devices found.", "devices": []}

    duplicate_seconds = max(int(settings.duplicate_seconds or DEFAULT_DUPLICATE_SECONDS), 0)
    all_events = []
    results = []
    totals = {
        "fetched": 0,
        "processed": 0,
        "movement_created": 0,
        "sessions": 0,
        "checkins": 0,
        "unmatched": 0,
        "errors": 0,
    }

    for device in devices:
        try:
            raw_events = _fetch_events(device, from_datetime, to_datetime)
            normalized = _normalize_device_events(device, raw_events, duplicate_seconds)
            all_events.extend(normalized)
            totals["fetched"] += len(raw_events)
            totals["processed"] += len(normalized)

            frappe.db.set_value(
                "Biometric Device",
                device.name,
                {
                    "last_sync": frappe.utils.now_datetime(),
                    "last_sync_status": f"Fetched {len(raw_events)}; processed {len(normalized)} employee events",
                },
                update_modified=False,
            )

            results.append({
                "status": "success",
                "device": device.device_name or device.ip,
                "ip": device.ip,
                "serial_number": device.serial_number,
                "fetched": len(raw_events),
                "processed": len(normalized),
            })
        except Exception as exc:
            totals["errors"] += 1
            frappe.log_error(
                frappe.get_traceback(),
                f"Hikvision movement sync failed: {device.device_name or device.ip}",
            )
            results.append({
                "status": "error",
                "device": device.device_name or device.ip,
                "ip": device.ip,
                "message": str(exc),
            })

    device_map = {
        (d.serial_number or d.device_id or d.ip): d
        for d in devices
    }
    affected = set()

    for event in all_events:
        device = device_map.get(event["device_serial"])
        if not device:
            continue

        log_date = _day_from_event(event["event_dt"], device.timezone or DEFAULT_TIMEZONE)
        log = _get_or_create_daily_log(event["employee"], log_date)

        try:
            if _save_new_movement_event(log, device, event):
                totals["movement_created"] += 1
                affected.add(log.name)
        except Exception:
            totals["errors"] += 1
            frappe.log_error(
                frappe.get_traceback(),
                f"Hikvision movement event save failed: {event['event_key']}",
            )

    for log_name in affected:
        try:
            log = frappe.get_doc(MOVEMENT_DOCTYPE, log_name)
            result = _reconcile_daily_log(log)
            totals["sessions"] += result["sessions"]
            totals["checkins"] += result["checkins"]
        except Exception:
            totals["errors"] += 1
            frappe.log_error(
                frappe.get_traceback(),
                f"Hikvision movement reconciliation failed: {log_name}",
            )

    frappe.db.commit()

    return {
        "status": "success" if totals["errors"] == 0 else "partial",
        **totals,
        "devices": results,
        "message": (
            f"Fetched {totals['fetched']} events; stored {totals['movement_created']} "
            f"new movement events; reconciled {totals['sessions']} device sessions."
        ),
    }


def sync_device(device_name, from_datetime, to_datetime):
    """Compatibility wrapper for callers that synchronize one device."""
    settings = _settings()
    device = next((d for d in settings.devices or [] if d.name == device_name), None)
    if not device:
        return {"status": "error", "message": f"Biometric Device {device_name} was not found."}
    if not device.enabled:
        return {"status": "error", "device": device.device_name or device.ip, "message": "Device is disabled"}

    try:
        raw_events = _fetch_events(device, from_datetime, to_datetime)
        duplicate_seconds = max(int(settings.duplicate_seconds or DEFAULT_DUPLICATE_SECONDS), 0)
        normalized = _normalize_device_events(device, raw_events, duplicate_seconds)
        created = 0
        affected = set()

        for event in normalized:
            log_date = _day_from_event(event["event_dt"], device.timezone or DEFAULT_TIMEZONE)
            log = _get_or_create_daily_log(event["employee"], log_date)
            if _save_new_movement_event(log, device, event):
                created += 1
                affected.add(log.name)

        sessions = 0
        checkins = 0
        for log_name in affected:
            result = _reconcile_daily_log(frappe.get_doc(MOVEMENT_DOCTYPE, log_name))
            sessions += result["sessions"]
            checkins += result["checkins"]

        frappe.db.commit()
        return {
            "status": "success",
            "device": device.device_name or device.ip,
            "ip": device.ip,
            "serial_number": device.serial_number,
            "fetched": len(raw_events),
            "processed": len(normalized),
            "movement_created": created,
            "sessions": sessions,
            "checkins": checkins,
        }
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), f"Hikvision single-device sync failed: {device.device_name or device.ip}")
        return {"status": "error", "device": device.device_name or device.ip, "ip": device.ip, "message": str(exc)}
