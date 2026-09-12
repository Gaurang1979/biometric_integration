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

import hashlib

import frappe
from frappe.utils import get_datetime

from biometric_integration.biometric_integration.doctype.biometric_field_mapping_settings.biometric_field_mapping_settings import (
	get_mapping_rows,
)


def _event_key(employee, time, source_event_id=None, device_id=None):
	if source_event_id:
		raw = f"mobile|{employee}|{source_event_id}"
	else:
		raw = f"mobile|{employee}|{time}|{device_id or ''}"
	return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _create_mobile_checkin(employee, time, log_type=None, latitude=None, longitude=None, device_id=None, source_event_id=None):
	key = _event_key(employee, time, source_event_id, device_id)

	if frappe.db.exists("Employee Checkin", {"biometric_event_id": key}):
		return {"status": "duplicate", "employee": employee, "time": str(time)}

	if not frappe.db.exists("Employee", employee):
		return {"status": "error", "employee": employee, "message": "Unknown employee"}

	doc = frappe.new_doc("Employee Checkin")
	doc.employee = employee
	doc.time = get_datetime(time)
	if log_type:
		doc.log_type = log_type
	doc.device_id = device_id or "Mobile App"
	if latitude is not None:
		doc.latitude = latitude
	if longitude is not None:
		doc.longitude = longitude
	if hasattr(doc, "biometric_event_id"):
		doc.biometric_event_id = key
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	from biometric_integration.biometric_integration.anti_passback import check_and_flag

	try:
		check_and_flag(employee, doc.device_id, doc.time, doc.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Anti-Passback Check Error")

	return {"status": "created", "employee": employee, "time": str(time), "name": doc.name}


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
	fields mapped per Biometric Field Mapping Settings (target: Mobile App)."""
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
