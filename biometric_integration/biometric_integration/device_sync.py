# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Direct multi-device Hikvision sync.

Replaces the old single-device `sync_attendance()` and the HikCentral-CSV
path. Polls every enabled "Biometric Device" over ISAPI. Every raw punch is
recorded into that employee's monthly "Employee Movement" log, and the
day's first/last punch is reconciled straight into the standard ERPNext HR
"Employee Checkin" doctype (what Shift Type auto-attendance / Payroll
actually consume) - see movement.py and reconciliation.py.
"""

from datetime import timedelta

import frappe
import requests
from frappe.utils import get_datetime, now_datetime
from requests.auth import HTTPDigestAuth

ACS_MAJOR = 5
ACS_MINOR = 75  # Card/Face/Fingerprint authentication success event
BATCH_SIZE = 30
MAX_RECORDS_PER_RUN = 5000


def get_enabled_devices():
	return frappe.get_all(
		"Biometric Device",
		filters={"enabled": 1},
		fields=["name", "device_name", "ip", "port", "protocol", "username", "timezone_offset", "sync_lookback_minutes"],
	)


def _employee_for_device_no(employee_no):
	"""Match a device employeeNo against Employee.attendance_device_id (ERPNext standard field)."""
	return frappe.db.get_value(
		"Employee",
		{"attendance_device_id": employee_no, "status": "Active"},
		"name",
	)


def _process_punch(device_name, employee, event_dt):
	"""Record the raw punch in Employee Movement, then try to reconcile it into
	Employee Checkin right away (works if a Shift Assignment already resolves
	for this employee/date). If not, it stays 'Pending Shift' in Employee
	Movement until the scheduled reconcile_all_pending catches it later -
	e.g. once HR assigns the Shift retroactively."""
	from biometric_integration.biometric_integration import movement as movement_mod
	from biometric_integration.biometric_integration import reconciliation

	movement, row, is_new = movement_mod.add_punch(employee, event_dt, device_name)
	if not is_new:
		return "duplicate"

	reconciliation.reconcile_day(employee, event_dt.date(), row)
	movement.save(ignore_permissions=True)

	checkin_name = row.get("checkout_ref") or row.get("checkin_ref")
	if checkin_name:
		from biometric_integration.biometric_integration.anti_passback import check_and_flag

		try:
			check_and_flag(employee, device_name, event_dt, checkin_name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Anti-Passback Check Error")

	return "created"


def _fetch_and_store_from_device(device, decrypted_password, start_dt, end_dt):
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	url = f"{base_url}/ISAPI/AccessControl/AcsEvent?format=json"
	headers = {"Content-Type": "application/json"}
	tz_offset = device.timezone_offset or "+00:00"

	start_time = start_dt.strftime(f"%Y-%m-%dT%H:%M:%S{tz_offset}")
	end_time = end_dt.strftime(f"%Y-%m-%dT%H:%M:%S{tz_offset}")

	payload = {
		"AcsEventCond": {
			"searchID": frappe.generate_hash(length=8),
			"searchResultPosition": 0,
			"maxResults": BATCH_SIZE,
			"major": ACS_MAJOR,
			"minor": ACS_MINOR,
			"startTime": start_time,
			"endTime": end_time,
		}
	}

	auth = HTTPDigestAuth(device.username, decrypted_password)

	created = duplicates = missing_employees = errors = 0
	position = 0

	while position < MAX_RECORDS_PER_RUN:
		payload["AcsEventCond"]["searchResultPosition"] = position
		response = requests.post(url, auth=auth, headers=headers, json=payload, verify=False, timeout=60)

		if response.status_code != 200:
			frappe.log_error(
				f"Device: {device.device_name}\nHTTP {response.status_code}: {response.text[:500]}",
				"Biometric Device Sync Error",
			)
			errors += 1
			break

		data = response.json()
		events = data.get("AcsEvent", {}).get("InfoList", [])
		if not events:
			break

		for log in events:
			emp_no = log.get("employeeNoString")
			event_timestamp = log.get("time", "")
			if not emp_no or not event_timestamp:
				continue

			try:
				event_dt = datetime.strptime(event_timestamp[:19], "%Y-%m-%dT%H:%M:%S")
			except ValueError:
				continue

			employee = _employee_for_device_no(emp_no)
			if not employee:
				missing_employees += 1
				continue

			try:
				result = _process_punch(device.device_name, employee, event_dt)
				if result == "created":
					created += 1
				else:
					duplicates += 1
			except Exception:
				errors += 1
				frappe.log_error(frappe.get_traceback(), "Biometric Punch Processing Error")

		position += len(events)
		if len(events) < BATCH_SIZE:
			break

	return {"created": created, "duplicates": duplicates, "missing_employees": missing_employees, "errors": errors}


@frappe.whitelist()
def sync_device(device_name, from_datetime=None, to_datetime=None):
	"""Sync a single device. Can be called manually with an explicit window, or
	from the scheduler with the device's own lookback window."""
	device = frappe.get_doc("Biometric Device", device_name)
	if not device.enabled:
		return {"status": "skipped", "message": "Device is disabled."}

	decrypted_password = device.get_password("password")
	end_dt = get_datetime(to_datetime) if to_datetime else now_datetime()
	start_dt = (
		get_datetime(from_datetime)
		if from_datetime
		else end_dt - timedelta(minutes=device.sync_lookback_minutes or 120)
	)

	try:
		result = _fetch_and_store_from_device(device, decrypted_password, start_dt, end_dt)
		frappe.db.set_value(
			"Biometric Device",
			device.name,
			{
				"last_sync_datetime": now_datetime(),
				"last_sync_status": (
					f"OK - created {result['created']}, duplicates {result['duplicates']}, "
					f"missing employees {result['missing_employees']}, errors {result['errors']}"
				),
			},
		)
		frappe.db.commit()
		return {"status": "success", **result}
	except requests.exceptions.RequestException as e:
		frappe.db.set_value("Biometric Device", device.name, "last_sync_status", f"Network error: {e}")
		frappe.db.commit()
		return {"status": "error", "message": str(e)}


@frappe.whitelist()
def sync_all_devices():
	"""Scheduled entry point: syncs every enabled device."""
	results = {}
	for device in get_enabled_devices():
		results[device.device_name] = sync_device(device.name)
	return results
