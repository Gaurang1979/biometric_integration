# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe

from biometric_integration.biometric_integration.access_control import check_access_summary
from biometric_integration.biometric_integration.biometric_enrollment import check_enrollment_status


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"label": "Device", "fieldname": "device", "fieldtype": "Data", "width": 220},
		{"label": "Access", "fieldname": "access", "fieldtype": "Data", "width": 120},
		{"label": "Enrolled", "fieldname": "enrolled", "fieldtype": "Data", "width": 120},
		{"label": "Face on File", "fieldname": "face", "fieldtype": "Data", "width": 120},
	]

	employee = _resolve_employee(filters.get("employee"))
	if not employee:
		frappe.msgprint("No Employee record linked to your user, and no employee selected.")
		return columns, []

	is_hr = any(r in frappe.get_roles() for r in ("HR Manager", "HR User", "System Manager"))

	access = check_access_summary(employee)
	allowed = set(access.get("allowed", []))
	denied = set(access.get("denied", []))

	enrollment = {}
	if is_hr:
		# Live device enrollment status is a device-probing HR/admin action -
		# skip it for a plain employee's self-service view to avoid hitting
		# every device just because someone opened this report.
		try:
			enrollment = check_enrollment_status(employee).get("results", {})
		except Exception:
			enrollment = {}

	device_name_by_id = {d.name: d.device_name for d in frappe.get_all("Biometric Device", fields=["name", "device_name"])}

	rows = []
	for device_id in sorted(allowed | denied):
		enroll_info = enrollment.get(device_name_by_id.get(device_id, device_id), {})
		rows.append(
			{
				"device": device_name_by_id.get(device_id, device_id),
				"access": "Allowed" if device_id in allowed else "Denied",
				"enrolled": "Yes" if enroll_info.get("enrolled") else ("-" if not enroll_info else "No"),
				"face": "Yes" if enroll_info.get("has_face") else "-",
			}
		)

	return columns, rows


def _resolve_employee(requested_employee):
	is_hr = frappe.has_permission("Employee", "read", user=frappe.session.user) and any(
		r in frappe.get_roles() for r in ("HR Manager", "HR User", "System Manager")
	)

	if requested_employee and is_hr:
		return requested_employee

	# Default / non-HR: only ever your own record.
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
