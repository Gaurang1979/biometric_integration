# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Visitor/temporary badges. Unlike Employee (default-allow-everywhere,
opt-out via access rules), a Visitor is default-deny: with no rows in
`device_access`, they are enrolled NOWHERE. This is deliberate - visitors
should be explicitly scoped, not accidentally get building-wide access.
"""

import frappe
import requests
from requests.auth import HTTPDigestAuth

from biometric_integration.biometric_integration.access_control import _devices_in_location
from biometric_integration.biometric_integration.biometric_enrollment import _device_doc, _push_face_to_device
from biometric_integration.biometric_integration.access_control import _delete_user_from_device
from biometric_integration.biometric_integration.doctype.biometric_audit_log.biometric_audit_log import log_action


def _allowed_devices_for_visitor(visitor_doc):
	allowed = set()
	denied = set()
	for row in visitor_doc.device_access:
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


def _ensure_visitor_on_device(device, visitor_doc):
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	headers = {"Content-Type": "application/json"}
	auth = HTTPDigestAuth(device.username, device.get_password("password"))
	user_info = {"employeeNo": str(visitor_doc.visitor_code), "name": visitor_doc.visitor_name}

	modify_url = f"{base_url}/ISAPI/AccessControl/UserInfo/Modify?format=json"
	response = requests.put(modify_url, auth=auth, headers=headers, json={"UserInfo": user_info}, verify=False, timeout=20)
	if response.status_code == 200:
		return {"status": "success", "action": "modify"}

	add_url = f"{base_url}/ISAPI/AccessControl/UserInfo/Record?format=json"
	response = requests.post(add_url, auth=auth, headers=headers, json={"UserInfo": user_info}, verify=False, timeout=20)
	if response.status_code == 200:
		return {"status": "success", "action": "add"}

	return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:300]}"}


@frappe.whitelist()
def provision_visitor(visitor):
	frappe.only_for(("System Manager", "HR Manager"))
	visitor_doc = frappe.get_doc("Biometric Visitor", visitor)

	if visitor_doc.status != "Active":
		return {"status": "error", "message": f"Visitor status is '{visitor_doc.status}', not Active."}

	allowed = _allowed_devices_for_visitor(visitor_doc)
	if not allowed:
		return {"status": "error", "message": "No devices/locations allowed - add rows to Allowed Devices / Locations first."}

	image_bytes = None
	if visitor_doc.face_image:
		file_doc = frappe.get_all("File", filters={"file_url": visitor_doc.face_image}, fields=["name"], limit_page_length=1)
		if file_doc:
			image_bytes = frappe.get_doc("File", file_doc[0].name).get_content()

	log_lines = []
	for device_name in allowed:
		device = _device_doc(device_name)
		result = _ensure_visitor_on_device(device, visitor_doc)
		log_lines.append(f"{device.device_name}: user {result['status']}")

		if image_bytes and result["status"] == "success":
			# reuse the employee face-push helper - it only reads attendance_device_id + employee_name,
			# both of which a lightweight shim object below provides.
			shim = frappe._dict(attendance_device_id=visitor_doc.visitor_code, employee_name=visitor_doc.visitor_name)
			face_result = _push_face_to_device(device, shim, image_bytes)
			log_lines.append(f"{device.device_name}: face {face_result['status']}")

		log_action(
			"Visitor Provision",
			"Success" if result["status"] == "success" else "Failed",
			device=device_name,
			details=f"Visitor {visitor_doc.visitor_name} ({visitor_doc.visitor_code}): {result.get('message', 'ok')}",
		)

	visitor_doc.db_set("provisioning_log", "\n".join(log_lines))
	frappe.db.commit()
	return {"status": "done", "log": log_lines}


@frappe.whitelist()
def revoke_visitor(visitor, new_status="Revoked"):
	frappe.only_for(("System Manager", "HR Manager"))
	visitor_doc = frappe.get_doc("Biometric Visitor", visitor)

	log_lines = []
	for device in frappe.get_all("Biometric Device", filters={"enabled": 1}, fields=["name", "device_name"]):
		device_doc = _device_doc(device.name)
		result = _delete_user_from_device(device_doc, visitor_doc.visitor_code)
		log_lines.append(f"{device.device_name}: revoke {result['status']}")
		log_action(
			"Visitor Expiry" if new_status == "Expired" else "Revoke",
			"Success" if result["status"] == "success" else "Failed",
			device=device.name,
			details=f"Visitor {visitor_doc.visitor_name} ({visitor_doc.visitor_code}): {result.get('message', 'ok')}",
		)

	visitor_doc.db_set("status", new_status)
	visitor_doc.db_set("provisioning_log", "\n".join(log_lines))
	frappe.db.commit()
	return {"status": "done", "log": log_lines}


@frappe.whitelist()
def expire_visitors():
	"""Scheduled: revoke and mark Expired any Active visitor past valid_to."""
	overdue = frappe.get_all(
		"Biometric Visitor",
		filters={"status": "Active", "valid_to": ["<", frappe.utils.now_datetime()]},
		pluck="name",
	)
	for visitor in overdue:
		try:
			revoke_visitor(visitor, new_status="Expired")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Visitor Auto-Expiry Error")
	return {"expired": len(overdue)}
