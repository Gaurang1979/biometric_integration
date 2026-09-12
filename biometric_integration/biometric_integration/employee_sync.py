# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Pushes Employee master changes out to Hikvision devices (ISAPI UserInfo)
and/or a mobile app webhook, using the mapping configured in
"Biometric Field Mapping Settings". Hooked from Employee after_insert /
on_update in hooks.py. Runs in a background job so it never slows down
saving an Employee record.
"""

import requests
import frappe
from requests.auth import HTTPDigestAuth

from biometric_integration.biometric_integration.doctype.biometric_field_mapping_settings.biometric_field_mapping_settings import (
	get_mapping_rows,
)


def queue_employee_sync(doc, method=None):
	if not doc.get("attendance_device_id"):
		return
	frappe.enqueue(
		"biometric_integration.biometric_integration.employee_sync.sync_employee",
		queue="short",
		employee=doc.name,
		enqueue_after_commit=True,
	)


def _build_payload(employee_doc, rows):
	payload = {}
	for row in rows:
		payload[row.external_fieldname] = employee_doc.get(row.erpnext_fieldname)
	return payload


def _push_to_device(device, employee_doc, rows):
	emp_no = employee_doc.attendance_device_id
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	headers = {"Content-Type": "application/json"}
	auth = HTTPDigestAuth(device.username, device.get_password("password"))

	user_info = _build_payload(employee_doc, rows)
	user_info["employeeNo"] = str(emp_no)

	# Try Modify first (existing user); fall back to Add for new hires.
	modify_url = f"{base_url}/ISAPI/AccessControl/UserInfo/Modify?format=json"
	response = requests.put(
		modify_url, auth=auth, headers=headers, json={"UserInfo": user_info}, verify=False, timeout=20
	)

	if response.status_code == 200:
		return {"status": "success", "action": "modify"}

	add_url = f"{base_url}/ISAPI/AccessControl/UserInfo/Record?format=json"
	response = requests.post(
		add_url, auth=auth, headers=headers, json={"UserInfo": user_info}, verify=False, timeout=20
	)
	if response.status_code == 200:
		return {"status": "success", "action": "add"}

	return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:300]}"}


@frappe.whitelist()
def sync_employee(employee):
	settings = frappe.get_single("Biometric Field Mapping Settings")
	employee_doc = frappe.get_doc("Employee", employee)

	if settings.enable_employee_push_to_devices and not settings.enable_device_access_control:
		device_rows = get_mapping_rows("Hikvision Device", direction="ERPNext to External")
		if device_rows:
			for device in frappe.get_all("Biometric Device", filters={"enabled": 1}, fields=["name"]):
				device_doc = frappe.get_doc("Biometric Device", device.name)
				try:
					result = _push_to_device(device_doc, employee_doc, device_rows)
					if result["status"] != "success":
						frappe.log_error(
							f"Employee {employee} -> {device_doc.device_name}: {result['message']}",
							"Employee Push to Device Failed",
						)
				except Exception:
					frappe.log_error(frappe.get_traceback(), "Employee Push to Device Error")

	if settings.enable_employee_push_to_mobile and settings.mobile_employee_webhook_url:
		mobile_rows = get_mapping_rows("Mobile App", direction="ERPNext to External")
		if mobile_rows:
			payload = _build_payload(employee_doc, mobile_rows)
			try:
				requests.post(settings.mobile_employee_webhook_url, json=payload, timeout=15)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Employee Push to Mobile Webhook Error")

	if settings.enable_device_access_control:
		from biometric_integration.biometric_integration.access_control import sync_employee_access

		try:
			sync_employee_access(employee)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Employee Device Access Sync Error")
