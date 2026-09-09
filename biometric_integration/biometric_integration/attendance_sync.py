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
ATTENDANCE_RELEASE_DELAY_HOURS = 12


def _as_local_naive(event_dt, timezone_name):
    return event_dt.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)


def _month_from_event(event_dt, timezone_name):
    return event_dt.astimezone(ZoneInfo(timezone_name)).date().replace(day=1)


def _event_value(event, *names):
    for name in names:
        value = event.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _get_or_create_monthly_log(employee, month):
    name = frappe.db.get_value(
        MOVEMENT_DOCTYPE,
        {"employee": employee, "month": month},
        "name",
        order_by="creation asc",
    )
    if name:
        return frappe.get_doc(MOVEMENT_DOCTYPE, name)

    doc = frappe.new_doc(MOVEMENT_DOCTYPE)
    doc.employee = employee
    doc.employee_name = frappe.db.get_value("Employee", employee, "employee_name") or ""
    doc.month = month
    doc.log_date = month
    doc.insert(ignore_permissions=True)
    return doc


def _event_exists(event_key):
    return frappe.db.exists(MOVEMENT_ENTRY_DOCTYPE, {"event_key": event_key})


def _append_event(log, device, event):
    if _event_exists(event["event_key"]):
        return False

    timezone_name = device.timezone or DEFAULT_TIMEZONE
    local_time = _as_local_naive(event["event_dt"], timezone_name)
    row = log.append("movement_entries", {})
    row.event_date = local_time.date()
    row.event_time = local_time
    row.device_name = device.device_name or device.ip
    row.location = device.device_name or device.ip
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
    row.event_key = event["event_key"]
    return True


def _save_new_movement_event(log, device, event):
    if _event_exists(event["event_key"]):
        return False
    if not _append_event(log, device, event):
        return False
    try:
        log.save(ignore_permissions=True)
        return True
    except frappe.DuplicateEntryError:
        frappe.logger().warning(
            "Duplicate Hikvision movement event skipped: %s", event["event_key"]
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
            "event_date",
            "location",
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


def _stable_session_key(employee, day, first_event_key):
    digest = sha1(f"{employee}|{day}|{first_event_key}".encode()).hexdigest()[:24]
    return f"HIKSESSION-{digest}"


def _sessionize(rows):
    sessions = []
    current = None
    for row in rows:
        day = row.event_time.date() if row.event_time else None
        identity = _device_identity(row)
        if (
            current is None
            or day != current["day"]
            or identity != current["device_identity"]
        ):
            current = {"day": day, "device_identity": identity, "rows": []}
            sessions.append(current)
        current["rows"].append(row)
    return sessions


def _find_checkin_by_session(session_key):
    return frappe.db.get_value(
        "Employee Checkin",
        {"biometric_session_key": session_key},
        ["name", "employee", "time", "log_type", "device_id", "biometric_event_key"],
        as_dict=True,
    )


def _find_checkin_by_event_key(event_key):
    meta = frappe.get_meta("Employee Checkin")
    if not meta.has_field("biometric_event_key") or not event_key:
        return None
    return frappe.db.get_value(
        "Employee Checkin",
        {"biometric_event_key": event_key},
        ["name", "employee", "time", "log_type", "device_id", "biometric_event_key", "biometric_session_key"],
        as_dict=True,
    )


def _find_existing_checkin(employee, row, log_type, session_key):
    """Find an existing check-in so a deleted/reimported movement log never creates a duplicate."""
    existing = _find_checkin_by_event_key(row.event_key)
    if existing:
        return existing

    existing = _find_checkin_by_session(f"{session_key}:{log_type}")
    if existing:
        return existing

    # Final fallback for records created before the biometric session/event keys
    # were added. Match the same employee, timestamp, device and log type.
    filters = {
        "employee": employee,
        "time": row.event_time,
        "log_type": log_type,
        "device_id": row.device_serial_number or row.device_name,
    }
    name = frappe.db.get_value("Employee Checkin", filters, "name")
    if name:
        return frappe.db.get_value(
            "Employee Checkin",
            name,
            ["name", "employee", "time", "log_type", "device_id", "biometric_event_key", "biometric_session_key"],
            as_dict=True,
        )
    return None


def _get_device_for_row(row):
    settings = _settings()
    serial = (row.device_serial_number or "").strip()
    name = (row.device_name or "").strip()
    for device in settings.devices or []:
        ds = (device.serial_number or device.device_id or device.ip or "").strip()
        dn = (device.device_name or "").strip()
        if serial and serial == ds:
            return device
        if name and name == dn:
            return device
    return None


def _get_shift_assignment(employee, event_time):
    if not frappe.db.exists("DocType", "Shift Assignment"):
        return None

    event_date = event_time.date()
    assignments = frappe.get_all(
        "Shift Assignment",
        filters={
            "employee": employee,
            "docstatus": 1,
            "start_date": ["<=", event_date],
        },
        fields=["name", "shift_type", "start_date", "end_date"],
        order_by="start_date desc, creation desc",
        limit_page_length=20,
    )
    for assignment in assignments:
        end_date = assignment.end_date
        if end_date and end_date < event_date:
            continue
        if assignment.shift_type:
            return assignment
    return None


def _get_shift_release_time(employee, event_time):
    """Return Shift End + 12h for the employee's assigned shift on event date."""
    assignment = _get_shift_assignment(employee, event_time)
    if not assignment:
        return None

    shift_type = frappe.db.get_value(
        "Shift Type",
        assignment.shift_type,
        ["start_time", "end_time"],
        as_dict=True,
    )
    if not shift_type or shift_type.end_time is None:
        return None

    event_date = event_time.date()
    end_time = shift_type.end_time
    if isinstance(end_time, str):
        try:
            end_time = datetime.strptime(end_time, "%H:%M:%S").time()
        except ValueError:
            try:
                end_time = datetime.strptime(end_time, "%H:%M").time()
            except ValueError:
                return None

    shift_end = datetime.combine(event_date, end_time)
    start_time = shift_type.start_time
    if isinstance(start_time, str):
        try:
            start_time = datetime.strptime(start_time, "%H:%M:%S").time()
        except ValueError:
            try:
                start_time = datetime.strptime(start_time, "%H:%M").time()
        except ValueError:
            start_time = None

    if start_time and end_time < start_time:
        shift_end += timedelta(days=1)

    return shift_end + timedelta(hours=ATTENDANCE_RELEASE_DELAY_HOURS)


def _attendance_is_released(employee, event_time):
    release_time = _get_shift_release_time(employee, event_time)
    if release_time is None:
        return False, None
    now = frappe.utils.now_datetime()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return now >= release_time, release_time


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
            f"Latitude and longitude are required for biometric check-in. Device '{row.device_name}' ({row.device_serial_number}) has no configured coordinates."
        )

    full_key = f"{session_key}:{log_type}"
    existing = _find_existing_checkin(employee, row, log_type, session_key)
    if existing:
        checkin = frappe.get_doc("Employee Checkin", existing.name)
        changed = False
        values = {
            "employee": employee,
            "time": row.event_time,
            "log_type": log_type,
            "device_id": row.device_serial_number or row.device_name,
            "latitude": latitude,
            "longitude": longitude,
            "biometric_session_key": full_key,
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
    checkin.biometric_session_key = full_key
    if meta.has_field("biometric_event_key"):
        checkin.biometric_event_key = row.event_key
    if meta.has_field("biometric_movement_log"):
        checkin.biometric_movement_log = row.parent
    try:
        checkin.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        # A legacy/native unique constraint may find an older check-in that
        # predates the biometric keys. Re-read it and update instead of failing.
        existing = _find_existing_checkin(employee, row, log_type, session_key)
        if not existing:
            raise
        checkin = frappe.get_doc("Employee Checkin", existing.name)
        checkin.employee = employee
        checkin.time = row.event_time
        checkin.log_type = log_type
        checkin.device_id = row.device_serial_number or row.device_name
        checkin.latitude = latitude
        checkin.longitude = longitude
        checkin.biometric_session_key = full_key
        if meta.has_field("biometric_event_key"):
            checkin.biometric_event_key = row.event_key
        if meta.has_field("biometric_movement_log"):
            checkin.biometric_movement_log = row.parent
        checkin.save(ignore_permissions=True)
    return checkin.name


def _reconcile_monthly_log(log):
    rows = _load_events_for_log(log)
    if not rows:
        return {"sessions": 0, "checkins": 0, "pending": 0}

    sessions = _sessionize(rows)
    checkins = 0
    pending = 0
    for session in sessions:
        first = session["rows"][0]
        last = session["rows"][-1]
        session_key = _stable_session_key(log.employee, session["day"], first.event_key)

        for index, row in enumerate(session["rows"]):
            direction = (
                "IN"
                if index == 0
                else ("OUT" if index == len(session["rows"]) - 1 else "LOG")
            )
            frappe.db.set_value(
                MOVEMENT_ENTRY_DOCTYPE,
                row.name,
                {
                    "event_date": row.event_time.date() if row.event_time else None,
                    "location": row.location or row.device_name,
                    "direction": direction,
                    "session_key": session_key,
                },
                update_modified=False,
            )

        released, release_time = _attendance_is_released(log.employee, first.event_time)
        if not released:
            pending += 1
            continue

        in_checkin = _create_or_update_checkin(
            log.employee, first, "IN", session_key
        )
        checkins += 1
        out_checkin = None
        if len(session["rows"]) > 1:
            out_checkin = _create_or_update_checkin(
                log.employee, last, "OUT", session_key
            )
            checkins += 1

        for row in session["rows"]:
            checkin_name = (
                in_checkin
                if row.name == first.name
                else (out_checkin if row.name == last.name else None)
            )
            frappe.db.set_value(
                MOVEMENT_ENTRY_DOCTYPE,
                row.name,
                "employee_checkin",
                checkin_name,
                update_modified=False,
            )

    return {"sessions": len(sessions), "checkins": checkins, "pending": pending}


def _find_employee(employee_no):
    return frappe.db.get_value(
        "Employee",
        {"attendance_device_id": employee_no, "status": "Active"},
        "name",
    )


def _normalize_device_events(device, raw_events, duplicate_seconds):
    timezone_name = device.timezone or DEFAULT_TIMEZONE
    normalized = []
    unmatched = []
    seen_unmatched = set()
    for raw in raw_events:
        if int(raw.get("major") or 0) != 5 or int(raw.get("minor") or 0) != 75:
            continue
        event_dt = _parse_event_time(raw.get("time"), timezone_name)
        employee_no = str(raw.get("employeeNoString") or "").strip()
        if not event_dt or not employee_no:
            continue
        employee = _find_employee(employee_no)
        if not employee:
            if employee_no not in seen_unmatched:
                unmatched.append(employee_no)
                seen_unmatched.add(employee_no)
            continue
        normalized.append(
            {
                **raw,
                "event_dt": event_dt,
                "employee": employee,
                "event_key": _event_key(device, raw),
                "device_serial": device.serial_number or device.device_id or device.ip,
            }
        )
    return _group_events(normalized, duplicate_seconds), unmatched


def _scheduler_start(to_datetime):
    local_now = to_datetime.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
    return local_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).replace(tzinfo=None)


def _pending_log_names(days=3):
    since = frappe.utils.now_datetime() - timedelta(days=days)
    rows = frappe.get_all(
        MOVEMENT_ENTRY_DOCTYPE,
        filters={"event_time": [">=", since]},
        fields=["parent"],
        limit_page_length=0,
    )
    return {row.parent for row in rows if row.parent}


def sync_all_devices(
    from_datetime=None, to_datetime=None, require_scheduler=False
):
    settings = _settings()
    if not settings.enabled:
        return {
            "status": "error",
            "message": "Biometric Integration is disabled.",
            "devices": [],
        }
    if require_scheduler and not settings.scheduler_enabled:
        return {
            "status": "skipped",
            "message": "Scheduler is disabled.",
            "devices": [],
        }
    if from_datetime is None or to_datetime is None:
        to_datetime = frappe.utils.now_datetime()
        from_datetime = _scheduler_start(to_datetime)

    devices = _get_enabled_devices()
    if not devices:
        return {
            "status": "error",
            "message": "No enabled Hikvision devices found.",
            "devices": [],
        }

    duplicate_seconds = max(
        int(settings.duplicate_seconds or DEFAULT_DUPLICATE_SECONDS), 0
    )
    all_events = []
    results = []
    totals = {
        "fetched": 0,
        "processed": 0,
        "movement_created": 0,
        "sessions": 0,
        "checkins": 0,
        "pending_sessions": 0,
        "unmatched": 0,
        "unmatched_employee_ids": [],
        "errors": 0,
    }

    for device in devices:
        try:
            raw_events = _fetch_events(device, from_datetime, to_datetime)
            normalized, unmatched = _normalize_device_events(
                device, raw_events, duplicate_seconds
            )
            all_events.extend(normalized)
            totals["fetched"] += len(raw_events)
            totals["processed"] += len(normalized)
            totals["unmatched"] += len(unmatched)
            totals["unmatched_employee_ids"].extend(
                f"{device.device_name or device.ip}: {employee_no}"
                for employee_no in unmatched
            )
            frappe.db.set_value(
                "Biometric Device",
                device.name,
                {
                    "last_sync": frappe.utils.now_datetime(),
                    "last_sync_status": f"Fetched {len(raw_events)}; processed {len(normalized)} employee events; unmatched {len(unmatched)}",
                },
                update_modified=False,
            )
            results.append(
                {
                    "status": "success",
                    "device": device.device_name or device.ip,
                    "ip": device.ip,
                    "serial_number": device.serial_number,
                    "fetched": len(raw_events),
                    "processed": len(normalized),
                    "unmatched": len(unmatched),
                    "unmatched_employee_ids": unmatched,
                }
            )
        except Exception as exc:
            totals["errors"] += 1
            frappe.log_error(
                frappe.get_traceback(),
                f"Hikvision movement sync failed: {device.device_name or device.ip}",
            )
            results.append(
                {
                    "status": "error",
                    "device": device.device_name or device.ip,
                    "ip": device.ip,
                    "message": str(exc),
                }
            )

    device_map = {
        (d.serial_number or d.device_id or d.ip): d for d in devices
    }
    affected = set()
    for event in all_events:
        device = device_map.get(event["device_serial"])
        if not device:
            continue
        month = _month_from_event(
            event["event_dt"], device.timezone or DEFAULT_TIMEZONE
        )
        log = _get_or_create_monthly_log(event["employee"], month)
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

    reconcile_logs = affected | _pending_log_names(days=3)
    for log_name in reconcile_logs:
        try:
            result = _reconcile_monthly_log(
                frappe.get_doc(MOVEMENT_DOCTYPE, log_name)
            )
            totals["sessions"] += result["sessions"]
            totals["checkins"] += result["checkins"]
            totals["pending_sessions"] += result["pending"]
        except Exception:
            totals["errors"] += 1
            frappe.log_error(
                frappe.get_traceback(),
                f"Hikvision movement reconciliation failed: {log_name}",
            )

    totals["unmatched_employee_ids"] = sorted(set(totals["unmatched_employee_ids"]))
    frappe.db.commit()
    if totals["unmatched"]:
        status = "partial"
    else:
        status = "success" if totals["errors"] == 0 else "partial"
    return {
        "status": status,
        **totals,
        "devices": results,
        "message": (
            f"Fetched {totals['fetched']} events; stored {totals['movement_created']} new movement events; "
            f"reconciled {totals['sessions']} device sessions; created/updated {totals['checkins']} checkins; "
            f"{totals['pending_sessions']} sessions are waiting for shift end + {ATTENDANCE_RELEASE_DELAY_HOURS} hours."
        ),
    }


def sync_device(device_name, from_datetime, to_datetime):
    settings = _settings()
    device = next(
        (d for d in settings.devices or [] if d.name == device_name),
        None,
    )
    if not device:
        return {
            "status": "error",
            "message": f"Device not found: {device_name}",
        }
    raw_events = _fetch_events(device, from_datetime, to_datetime)
    normalized, unmatched = _normalize_device_events(
        device,
        raw_events,
        max(int(settings.duplicate_seconds or DEFAULT_DUPLICATE_SECONDS), 0),
    )
    return {
        "status": "success" if not unmatched else "partial",
        "device": device_name,
        "fetched": len(raw_events),
        "processed": len(normalized),
        "unmatched": len(unmatched),
        "unmatched_employee_ids": unmatched,
    }
