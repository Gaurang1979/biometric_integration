# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
API surface for the on-site attendance mobile app.

Auth: use standard Frappe REST API Key/Secret (Authorization: token
<api_key>:<api_secret>) issued per mobile user from User > API Access.
Do not build a separate auth scheme - Frappe's is already
production-grade and works out of the box with these endpoints.

Endpoints:
  POST /api/method/biometric_integration.biometric_integration.mobile_api.mobile_checkin_push
  POST /api/method/biometric_integration.biometric_integration.mobile_api.mobile_checkin_bulk_push
  GET  /api/method/biometric_integration.biometric_integration.mobile_api.mobile_employee_list
"""

import frappe
from frappe.utils import get_datetime

from biometric_integration.biometric_integration.field_mapping import get_mapping_rows


def _create_mobile_checkin(employee, time, log_type=None, latitude=None, longitude=None, device_id=None, source_event_id=None):
	"""Same raw-punch-first flow as device_sync.py: record into Employee
	Movement, then try immediate reconciliation into Employee Checkin.
	Note: latitude/longitude are accepted for API compatibility but are not
	currently persisted onto the movement log or the reconciled checkin -
	only the punch time is."""
	if not frappe.db.exists("Employee", employee):
		return {"status": "error", "employee": employee, "message": "Unknown employee"}

	from biometric_integration.biometric_integration import movement as movement_mod
	from biometric_integration.biometric_integration import reconciliation

	event_dt = get_datetime(time)
	device_name = device_id or "Mobile App"

	movement, row, is_new = movement_mod.add_punch(employee, event_dt, device_name)
	if not is_new:
		return {"status": "duplicate", "employee": employee, "time": str(time)}

	reconciliation.reconcile_day(employee, event_dt.date(), row)
	movement.save(ignore_permissions=True)
	frappe.db.commit()

	checkin_name = row.get("checkout_ref") or row.get("checkin_ref")
	if checkin_name:
		from biometric_integration.biometric_integration.anti_passback import check_and_flag

		try:
			check_and_flag(employee, device_name, event_dt, checkin_name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Anti-Passback Check Error")

	return {
		"status": "created",
		"employee": employee,
		"time": str(time),
		"movement": movement.name,
		"checkin": checkin_name,
	}


@frappe.whitelist()
def mobile_checkin_push(employee, time, log_type=None, latitude=None, longitude=None, device_id=None, source_event_id=None):
	"""Push a single onsite attendance event from the mobile app."""
	return _create_mobile_checkin(employee, time, log_type, latitude, longitude, device_id, source_event_id)


@frappe.whitelist()
def mobile_checkin_bulk_push(events):
	"""Push a batch of events. `events` is a JSON list of dicts with the same
	keys as mobile_checkin_push (employee, time, log_type, latitude,
	longitude, device_id, source_event_id)."""
	if isinstance(events, str):
		events = frappe.parse_json(events)

	results = []
	for event in events:
		try:
			results.append(
				_create_mobile_checkin(
					event.get("employee"),
					event.get("time"),
					event.get("log_type"),
					event.get("latitude"),
					event.get("longitude"),
					event.get("device_id"),
					event.get("source_event_id"),
				)
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Mobile Checkin Bulk Push Error")
			results.append({"status": "error", "employee": event.get("employee")})

	return results


def _mapped_employee_payload(employee_doc, rows):
	payload = {}
	for row in rows:
		value = employee_doc.get(row.erpnext_fieldname)
		payload[row.external_fieldname] = value
	return payload


@frappe.whitelist()
def mobile_employee_list(modified_after=None):
	"""Return active employees for the mobile app to cache locally, with
	fields mapped per Biometric Integration Settings' Field Mapping tab (target: Mobile App)."""
	rows = get_mapping_rows("Mobile App", direction="ERPNext to External")
	filters = {"status": "Active"}
	if modified_after:
		filters["modified"] = [">", get_datetime(modified_after)]

	fieldnames = list({row.erpnext_fieldname for row in rows}) or ["name", "employee_name", "attendance_device_id"]
	if "name" not in fieldnames:
		fieldnames.append("name")

	employees = frappe.get_all("Employee", filters=filters, fields=fieldnames)

	if not rows:
		return employees

	out = []
	for emp in employees:
		row_payload = {}
		for row in rows:
			row_payload[row.external_fieldname] = emp.get(row.erpnext_fieldname)
		out.append(row_payload)
	return out
