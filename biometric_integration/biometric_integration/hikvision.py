from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import frappe
import requests
from requests.auth import HTTPDigestAuth
from frappe.utils.password import get_decrypted_password


EVENT_MAJOR = 5
EVENT_MINOR = 75
EVENT_PAGE_SIZE = 100
DEFAULT_DUPLICATE_SECONDS = 30
DEFAULT_TIMEZONE = "Asia/Kolkata"


def _settings():
    return frappe.get_single("Biometric Integration Settings")


def _get_device(device_name):
    settings = _settings()
    for row in settings.devices or []:
        if row.name == device_name:
            return row
    frappe.throw(f"Biometric Device {device_name} was not found in Biometric Integration Settings")


def _password(device):
    return get_decrypted_password("Biometric Device", device.name, "password")


def _auth(device):
    return HTTPDigestAuth(device.username, _password(device))


def _base_url(device):
    protocol = (device.protocol or "HTTP").strip().lower()
    if protocol not in ("http", "https"):
        protocol = "http"
    host = (device.ip or "").strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    port = int(device.port or (443 if protocol == "https" else 80))
    return f"{protocol}://{host}:{port}"


def _post_json(device, path, payload, timeout=60):
    return requests.post(f"{_base_url(device)}{path}", auth=_auth(device), headers={"Content-Type": "application/json"}, json=payload, verify=False, timeout=timeout)


def _get(device, path, timeout=30):
    return requests.get(f"{_base_url(device)}{path}", auth=_auth(device), verify=False, timeout=timeout)


def _parse_device_info(content):
    root = ET.fromstring(content)
    ns = {"ns": "http://www.isapi.org/ver20/XMLSchema"}

    def value(tag):
        node = root.find(f"ns:{tag}", ns)
        return node.text.strip() if node is not None and node.text else ""

    return {"device_name": value("deviceName"), "device_id": value("deviceID"), "model": value("model"), "serial_number": value("serialNumber"), "mac_address": value("macAddress")}


@frappe.whitelist()
def test_device(device_name):
    device = _get_device(device_name)
    try:
        response = _get(device, "/ISAPI/System/deviceInfo")
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code, "message": response.text[:1000]}
        return {"status": "success", "device": _parse_device_info(response.content)}
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), "Hikvision device test failed")
        return {"status": "error", "message": str(exc)}


@frappe.whitelist()
def test_all_devices():
    settings = _settings()
    results = []
    for row in settings.devices or []:
        if not row.enabled:
            continue
        result = test_device(row.name)
        results.append({"name": row.name, "device_name": row.device_name, **result})
    return {"devices": results}


@frappe.whitelist()
def fetch_device_info(device_name):
    device = _get_device(device_name)
    result = test_device(device_name)
    if result.get("status") != "success":
        return result
    info = result["device"]
    for fieldname in ("device_id", "model", "serial_number", "mac_address"):
        frappe.db.set_value("Biometric Device", device.name, fieldname, info.get(fieldname, ""), update_modified=False)
    if info.get("device_name") and not device.device_name:
        frappe.db.set_value("Biometric Device", device.name, "device_name", info["device_name"], update_modified=False)
    frappe.db.commit()
    return {"status": "success", "device": info}


def _event_payload(start_time, end_time, position, search_id):
    return {"AcsEventCond": {"searchID": search_id, "searchResultPosition": position, "maxResults": EVENT_PAGE_SIZE, "major": EVENT_MAJOR, "minor": EVENT_MINOR, "startTime": start_time, "endTime": end_time}}


def _fetch_events(device, from_datetime, to_datetime):
    timezone_name = device.timezone or DEFAULT_TIMEZONE
    start = _iso_with_offset(from_datetime, timezone_name)
    end = _iso_with_offset(to_datetime, timezone_name)
    events = []
    position = 0
    search_id = f"erpnext-{frappe.generate_hash(length=12)}"

    while True:
        response = _post_json(device, "/ISAPI/AccessControl/AcsEvent?format=json", _event_payload(start, end, position, search_id), timeout=90)
        if response.status_code != 200:
            raise RuntimeError(f"Hikvision HTTP {response.status_code}: {response.text[:2000]}")
        data = response.json().get("AcsEvent", {})
        page = data.get("InfoList") or []
        events.extend(page)
        total = int(data.get("totalMatches") or len(events))
        if not page or len(events) >= total or data.get("responseStatusStrg") != "MORE":
            break
        position += len(page)
        if position > 10000:
            raise RuntimeError("Hikvision event pagination exceeded 10,000 records; narrow the date range")
    return events


def _iso_with_offset(value, timezone_name):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone_name))
    else:
        value = value.astimezone(ZoneInfo(timezone_name))
    return value.isoformat(timespec="seconds")


def _parse_event_time(value, timezone_name):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone_name))
    return dt


def _group_events(events, duplicate_seconds):
    ordered = sorted(events, key=lambda e: (str(e.get("employeeNoString") or ""), str(e.get("device_serial") or ""), e.get("event_dt"), int(e.get("serialNo") or 0)))
    result = []
    previous = {}
    for event in ordered:
        key = (str(event.get("employeeNoString") or ""), str(event.get("device_serial") or ""))
        previous_event = previous.get(key)
        if previous_event:
            delta = (event["event_dt"] - previous_event["event_dt"]).total_seconds()
            if 0 <= delta <= duplicate_seconds:
                continue
        result.append(event)
        previous[key] = event
    return sorted(result, key=lambda e: e["event_dt"])


def _find_employee(employee_no):
    if not employee_no:
        return None
    return frappe.db.get_value("Employee", {"attendance_device_id": str(employee_no).strip(), "status": "Active"}, "name")


def _event_key(device, event):
    device_identity = device.serial_number or device.device_id or device.ip
    serial_no = event.get("serialNo")
    if serial_no is not None:
        return f"HIKVISION:{device_identity}:{serial_no}"
    return f"HIKVISION:{device_identity}:{event.get('employeeNoString')}:{event.get('time')}"


def _has_event_key(event_key):
    if frappe.get_meta("Employee Checkin").has_field("hikcentral_event_key"):
        return frappe.db.exists("Employee Checkin", {"hikcentral_event_key": event_key})
    return False


def _previous_log_type(employee, event_dt):
    rows = frappe.get_all("Employee Checkin", filters={"employee": employee, "time": ["<", event_dt]}, fields=["log_type"], order_by="time desc", limit=1)
    return "IN" if not rows or rows[0].log_type == "OUT" else "OUT"


def _create_checkin(device, event):
    employee_no = str(event.get("employeeNoString") or "").strip()
    employee = _find_employee(employee_no)
    if not employee:
        return "unmatched"
    key = _event_key(device, event)
    if _has_event_key(key):
        return "duplicate"
    meta = frappe.get_meta("Employee Checkin")
    if meta.has_field("latitude") and meta.has_field("longitude") and (device.latitude is None or device.longitude is None):
        return "missing_location"

    checkin = frappe.new_doc("Employee Checkin")
    checkin.employee = employee
    checkin.time = event["event_dt"].astimezone(ZoneInfo(device.timezone or DEFAULT_TIMEZONE)).replace(tzinfo=None)
    checkin.log_type = _previous_log_type(employee, checkin.time)
    checkin.device_id = device.serial_number or device.device_id or device.device_name or device.ip
    if meta.has_field("hikcentral_event_key"):
        checkin.hikcentral_event_key = key
    if meta.has_field("latitude") and meta.has_field("longitude"):
        checkin.latitude = device.latitude
        checkin.longitude = device.longitude
    checkin.insert(ignore_permissions=True)
    return "created"


def sync_device(device_name, from_datetime, to_datetime):
    settings = _settings()
    device = _get_device(device_name)
    if not device.enabled:
        return {"status": "error", "message": "Device is disabled"}
    try:
        raw_events = _fetch_events(device, from_datetime, to_datetime)
        timezone_name = device.timezone or DEFAULT_TIMEZONE
        normalized = []
        for raw in raw_events:
            if int(raw.get("major") or 0) != EVENT_MAJOR or int(raw.get("minor") or 0) != EVENT_MINOR:
                continue
            event_dt = _parse_event_time(raw.get("time"), timezone_name)
            if event_dt and raw.get("employeeNoString"):
                normalized.append({**raw, "event_dt": event_dt, "device_serial": device.serial_number or device.device_id or device.ip})
        duplicate_seconds = max(int(settings.duplicate_seconds or DEFAULT_DUPLICATE_SECONDS), 0)
        normalized = _group_events(normalized, duplicate_seconds)
        counts = {"created": 0, "duplicate": 0, "unmatched": 0, "missing_location": 0}
        for event in normalized:
            counts[_create_checkin(device, event)] += 1
        message = f"Fetched {len(raw_events)} events; processed {len(normalized)} successful authentication events"
        frappe.db.set_value("Biometric Device", device.name, {"last_sync": frappe.utils.now_datetime(), "last_sync_status": message}, update_modified=False)
        frappe.db.commit()
        return {"status": "success", "device": device.device_name, "fetched": len(raw_events), "processed": len(normalized), **counts}
    except Exception as exc:
        frappe.db.set_value("Biometric Device", device.name, {"last_sync": frappe.utils.now_datetime(), "last_sync_status": f"ERROR: {exc}"}, update_modified=False)
        frappe.db.commit()
        frappe.log_error(frappe.get_traceback(), f"Hikvision sync failed: {device.device_name}")
        return {"status": "error", "device": device.device_name, "message": str(exc)}


def sync_all_devices():
    settings = _settings()
    if not settings.enabled or not settings.scheduler_enabled:
        return []
    minutes = max(int(settings.scheduler_window_minutes or 15), 1)
    end = frappe.utils.now_datetime()
    start = end - timedelta(minutes=minutes)
    return [sync_device(row.name, start, end) for row in settings.devices or [] if row.enabled]
