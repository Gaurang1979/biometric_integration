# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Location/device-wise entry restriction.

Default behaviour (no rules configured for an employee): unrestricted -
enrolled on every enabled device, same as before this feature existed.
Once an employee has at least one row in their "Biometric Access" table,
only the devices/locations resolved from those rows (respecting
valid_from/valid_to and access_enabled) are allowed - everything else is
actively revoked (device-side user record deleted), not just skipped,
since a stale enrollment left on a device is itself a security gap.
"""

import frappe
import requests
from frappe.utils import getdate, nowdate
from requests.auth import HTTPDigestAuth

from biometric_integration.biometric_integration.biometric_enrollment import (
	_device_doc,
	_ensure_device_user,
	_get_devices,
	_push_face_to_device,
	_push_fingerprint_to_device,
)
from biometric_integration.biometric_integration.doctype.biometric_field_mapping_settings.biometric_field_mapping_settings import (
	get_mapping_rows,
)
from biometric_integration.biometric_integration.doctype.biometric_audit_log.biometric_audit_log import log_action
from biometric_integration.biometric_integration.employee_sync import _push_to_device


def _devices_in_location(location):
	return frappe.get_all("Biometric Device", filters={"location": location, "enabled": 1}, pluck="name")


def get_allowed_devices(employee):
	"""Returns None for "unrestricted" (no rules set), or a set of allowed
	device names (possibly empty, meaning explicitly no access anywhere)."""
	rows = frappe.get_all(
		"Employee Biometric Access Row",
		filters={"parent": employee, "parenttype": "Employee"},
		fields=["rule_type", "device", "location", "access_enabled", "valid_from", "valid_to"],
	)
	if not rows:
		return None

	today = getdate(nowdate())
	allowed = set()
	denied = set()

	for row in rows:
		if row.valid_from and today < getdate(row.valid_from):
			continue
		if row.valid_to and today > getdate(row.valid_to):
			continue

		if row.rule_type == "Device" and row.device:
			targets = {row.device}
		elif row.rule_type == "Location" and row.location:
			targets = set(_devices_in_location(row.location))
		else:
			continue

		if row.access_enabled:
			allowed |= targets
		else:
			denied |= targets

	return allowed - denied


def _delete_user_from_device(device, emp_no):
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	auth = HTTPDigestAuth(device.username, device.get_password("password"))
	url = f"{base_url}/ISAPI/AccessControl/UserInfo/Delete?format=json"
	payload = {"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": str(emp_no)}]}}
	try:
		response = requests.put(url, auth=auth, json=payload, verify=False, timeout=20)
		if response.status_code == 200:
			return {"status": "success"}
		# Many devices return 404/400 for "user doesn't exist" - treat that as
		# already-revoked rather than an error worth surfacing.
		if response.status_code in (400, 404):
			return {"status": "success", "message": "Already not present on device."}
		return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:200]}"}
	except requests.exceptions.RequestException as e:
		return {"status": "error", "message": f"Network error: {e}"}


@frappe.whitelist()
def sync_employee_access(employee):
	"""Enrolls the employee on every currently-allowed device and revokes
	them from every enabled device that isn't allowed. Safe to call
	repeatedly - both enroll and revoke are idempotent on the device side."""
	frappe.only_for(("System Manager", "HR Manager"))

	employee_doc = frappe.get_doc("Employee", employee)
	emp_no = employee_doc.attendance_device_id
	if not emp_no:
		return {"status": "error", "message": "Set Attendance Device ID on the employee first."}

	allowed = get_allowed_devices(employee)
	all_devices = {d["name"] for d in _get_devices()}
	allowed_set = all_devices if allowed is None else (allowed & all_devices)
	denied_set = all_devices - allowed_set

	template = frappe.get_doc("Employee Biometric Template", employee) if frappe.db.exists(
		"Employee Biometric Template", employee
	) else None

	device_rows = get_mapping_rows("Hikvision Device", direction="ERPNext to External")

	results = {"enrolled": {}, "revoked": {}}

	for device_name in allowed_set:
		device = _device_doc(device_name)

		# Apply the full field mapping (name, department, etc.) if configured;
		# otherwise fall back to the employeeNo + name minimum.
		user_info_result = _push_to_device(device, employee_doc, device_rows) if device_rows else _ensure_device_user(device, employee_doc)
		device_result = {"user_info": user_info_result}

		if template:
			if template.face_image:
				file_doc = frappe.get_all("File", filters={"file_url": template.face_image}, fields=["name"], limit_page_length=1)
				if file_doc:
					image_bytes = frappe.get_doc("File", file_doc[0].name).get_content()
					device_result["face"] = _push_face_to_device(device, employee_doc, image_bytes)
			for finger_id, fieldname in ((1, "fingerprint_1_template"), (2, "fingerprint_2_template")):
				tmpl = template.get(fieldname)
				if tmpl:
					device_result[f"fingerprint_{finger_id}"] = _push_fingerprint_to_device(device, employee_doc, finger_id, tmpl)

		results["enrolled"][device.device_name] = device_result
		log_action(
			"Enroll",
			"Success" if user_info_result.get("status") == "success" else "Failed",
			employee=employee,
			device=device_name,
			details=frappe.as_json(device_result),
		)

	for device_name in denied_set:
		device = _device_doc(device_name)
		revoke_result = _delete_user_from_device(device, emp_no)
		results["revoked"][device.device_name] = revoke_result
		log_action(
			"Revoke",
			"Success" if revoke_result.get("status") == "success" else "Failed",
			employee=employee,
			device=device_name,
			details=frappe.as_json(revoke_result),
		)

	return {"status": "done", "allowed_count": len(allowed_set), "denied_count": len(denied_set), "results": results}


@frappe.whitelist()
def check_access_summary(employee):
	"""Quick readout of which devices are currently allowed/denied per the
	configured rules, without contacting any device."""
	allowed = get_allowed_devices(employee)
	all_devices = [d["name"] for d in _get_devices()]
	if allowed is None:
		return {"status": "unrestricted", "allowed": all_devices, "denied": []}
	return {
		"status": "restricted",
		"allowed": sorted(allowed & set(all_devices)),
		"denied": sorted(set(all_devices) - allowed),
	}
