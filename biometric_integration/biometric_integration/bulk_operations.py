# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""Bulk enroll/revoke - select many employees + one device (or "all
enabled devices") and act on all of them in one call, instead of
one-employee-at-a-time via the Employee form buttons."""

import frappe

from biometric_integration.biometric_integration.access_control import _delete_user_from_device
from biometric_integration.biometric_integration.biometric_enrollment import _device_doc, _ensure_device_user
from biometric_integration.biometric_integration.doctype.biometric_audit_log.biometric_audit_log import log_action
from biometric_integration.biometric_integration.employee_sync import _push_to_device
from biometric_integration.biometric_integration.doctype.biometric_field_mapping_settings.biometric_field_mapping_settings import (
	get_mapping_rows,
)


@frappe.whitelist()
def bulk_sync_access(employees, device_name=None, action="enroll"):
	"""employees: JSON list of Employee names. device_name: a single
	Biometric Device, or omitted to mean "all enabled devices". action:
	"enroll" or "revoke"."""
	frappe.only_for(("System Manager", "HR Manager"))

	if isinstance(employees, str):
		employees = frappe.parse_json(employees)
	if not employees:
		return {"status": "error", "message": "No employees selected."}

	device_names = [device_name] if device_name else frappe.get_all("Biometric Device", filters={"enabled": 1}, pluck="name")
	if not device_names:
		return {"status": "error", "message": "No enabled device found."}

	device_rows = get_mapping_rows("Hikvision Device", direction="ERPNext to External")

	results = {}
	for employee in employees:
		employee_doc = frappe.get_doc("Employee", employee)
		emp_no = employee_doc.attendance_device_id
		if not emp_no:
			results[employee] = {"status": "error", "message": "No Attendance Device ID set."}
			continue

		per_device = {}
		for dname in device_names:
			device = _device_doc(dname)
			if action == "enroll":
				result = _push_to_device(device, employee_doc, device_rows) if device_rows else _ensure_device_user(device, employee_doc)
				log_action("Enroll", "Success" if result.get("status") == "success" else "Failed", employee=employee, device=dname, details="Bulk enroll")
			else:
				result = _delete_user_from_device(device, emp_no)
				log_action("Revoke", "Success" if result.get("status") == "success" else "Failed", employee=employee, device=dname, details="Bulk revoke")
			per_device[device.device_name] = result

		results[employee] = per_device

	return {"status": "done", "action": action, "results": results}
