# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import xml.etree.ElementTree as ET

import frappe
import requests
from frappe.model.document import Document
from requests.auth import HTTPDigestAuth


class BiometricDevice(Document):
	def before_save(self):
		self.fetch_device_info(silent=True)

	def base_url(self):
		return f"{self.protocol}://{self.ip}:{self.port}"

	def auth(self):
		return HTTPDigestAuth(self.username, self.get_password("password"))

	def fetch_device_info(self, silent=False):
		"""Populate read-only device info fields via ISAPI. Never blocks save on failure."""
		if not self.ip or not self.username or not self.get_password("password"):
			return
		try:
			url = f"{self.base_url()}/ISAPI/System/deviceInfo"
			response = requests.get(url, auth=self.auth(), timeout=10, verify=False)
			if response.status_code != 200:
				return

			root = ET.fromstring(response.content)
			ns = {"ns": "http://www.isapi.org/ver20/XMLSchema"}

			def _get(tag):
				el = root.find(f"ns:{tag}", ns)
				return el.text if el is not None else ""

			self.device_name = self.device_name or _get("deviceName")
			self.device_id = _get("deviceID")
			self.model = _get("model")
			self.device_serial_number = _get("serialNumber")
			self.mac_address = _get("macAddress")
			self.firmware_version = _get("firmwareVersion")
		except Exception as e:
			if not silent:
				raise
			frappe.log_error(f"Device info fetch failed for {self.name}: {e}", "Biometric Device Info")


@frappe.whitelist()
def test_connection(device_name):
	frappe.only_for(("System Manager", "HR Manager"))
	device = frappe.get_doc("Biometric Device", device_name)
	try:
		url = f"{device.base_url()}/ISAPI/System/deviceInfo"
		response = requests.get(url, auth=device.auth(), timeout=10, verify=False)
		if response.status_code == 200:
			return {"status": "success", "message": f"Connected to {device.ip}."}
		return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:200]}"}
	except requests.exceptions.RequestException as e:
		return {"status": "error", "message": f"Network error: {e}"}


@frappe.whitelist()
def get_employee_face(device_name, emp_no):
	"""Restricted to HR/System Manager - returns a face image URL or base64 blob, which is
	personal biometric data."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))
	device = frappe.get_doc("Biometric Device", device_name)
	url = f"{device.base_url()}/ISAPI/AccessControl/UserInfo/Search?format=json"
	headers = {"Content-Type": "application/json"}
	payload = {
		"UserInfoSearchCond": {
			"searchID": "face-fetch",
			"searchResultPosition": 0,
			"maxResults": 1,
			"EmployeeNoList": [{"employeeNo": str(emp_no)}],
		}
	}
	try:
		response = requests.post(url, auth=device.auth(), headers=headers, json=payload, verify=False, timeout=30)
		if response.status_code != 200:
			return {"status": "error", "message": f"HTTP {response.status_code}"}

		data = response.json()
		user_info = data.get("UserInfoSearch", {}).get("UserInfo", [])
		if not user_info:
			return {"status": "error", "message": "Employee not found"}

		face_url = user_info[0].get("faceURL")
		face_data = user_info[0].get("faceData")
		if face_url:
			return {"status": "success", "type": "url", "data": face_url}
		if face_data:
			return {"status": "success", "type": "base64", "data": face_data}
		return {"status": "error", "message": "No face found"}
	except Exception as e:
		frappe.log_error(f"Face fetch failed: {e}", "Biometric Face Fetch")
		return {"status": "error", "message": str(e)}


@frappe.whitelist()
def set_employee_name_on_device(device_name, emp_no, emp_name=None):
	frappe.only_for(("System Manager", "HR Manager"))
	device = frappe.get_doc("Biometric Device", device_name)
	if not emp_no:
		return {"status": "error", "message": "Employee No is required"}

	url = f"{device.base_url()}/ISAPI/AccessControl/UserInfo/Modify?format=json"
	headers = {"Content-Type": "application/json"}
	name_value = str(emp_name) if emp_name else ""
	payload = {"UserInfo": {"employeeNo": str(emp_no), "name": name_value}}

	try:
		response = requests.put(url, auth=device.auth(), headers=headers, json=payload, verify=False, timeout=20)
		if response.status_code == 200:
			return {"status": "success", "message": f"Name updated for employee {emp_no}"}
		return {"status": "error", "message": f"Device returned HTTP {response.status_code}: {response.text[:200]}"}
	except Exception as e:
		frappe.log_error(f"Set employee name failed: {e}", "Biometric Set Employee Name")
		return {"status": "error", "message": str(e)}
