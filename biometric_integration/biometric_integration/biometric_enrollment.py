# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Direct employee enrollment onto Hikvision devices from the ERPNext Employee
master - no HikCentral software involved.

Face enrollment uses the standard ISAPI face-upload pattern:
  1. Ensure the employee exists as a device user (UserInfo/Record or Modify).
  2. POST multipart/form-data to /ISAPI/AccessControl/UserFace/Record?format=json
     with a "FaceDataRecord" JSON part (faceLibType, FDID, FPID=employeeNo) and
     an "img" part (the JPEG bytes).
This is the widely-documented ISAPI face path and should work on most
Hikvision access-control terminals. Confirm against your exact model's
`GET /ISAPI/System/capabilities` if a call fails.

Fingerprint enrollment has no reliable universal remote-capture call - most
devices need a finger physically presented at a local USB enrollment reader
or the terminal itself. `trigger_fingerprint_capture()` below issues a
best-effort device-initiated capture request; treat it as experimental and
verify against your device's ISAPI capability document before relying on it.
"""

import base64

import frappe
import requests
from requests.auth import HTTPDigestAuth

FACE_LIB_TYPE = "blackFD"  # standard Hikvision access-control face library type
FDID = "1"


def _get_devices():
	return frappe.get_all("Biometric Device", filters={"enabled": 1}, fields=["name"])


def _device_doc(device_name):
	return frappe.get_doc("Biometric Device", device_name)


def _ensure_device_user(device, employee_doc):
	"""Create or update the base UserInfo record (employeeNo + name) before
	attaching a face - devices generally reject face uploads for an
	employeeNo that doesn't exist yet."""
	emp_no = employee_doc.attendance_device_id
	if not emp_no:
		return {"status": "error", "message": "Employee has no Attendance Device ID set."}

	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	headers = {"Content-Type": "application/json"}
	auth = HTTPDigestAuth(device.username, device.get_password("password"))
	user_info = {"employeeNo": str(emp_no), "name": employee_doc.employee_name}

	modify_url = f"{base_url}/ISAPI/AccessControl/UserInfo/Modify?format=json"
	response = requests.put(modify_url, auth=auth, headers=headers, json={"UserInfo": user_info}, verify=False, timeout=20)
	if response.status_code == 200:
		return {"status": "success"}

	record_url = f"{base_url}/ISAPI/AccessControl/UserInfo/Record?format=json"
	response = requests.post(record_url, auth=auth, headers=headers, json={"UserInfo": user_info}, verify=False, timeout=20)
	if response.status_code == 200:
		return {"status": "success"}

	return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:300]}"}


def _push_face_to_device(device, employee_doc, image_bytes):
	emp_no = employee_doc.attendance_device_id
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	auth = HTTPDigestAuth(device.username, device.get_password("password"))

	ensured = _ensure_device_user(device, employee_doc)
	if ensured["status"] != "success":
		return ensured

	url = f"{base_url}/ISAPI/AccessControl/UserFace/Record?format=json"
	face_meta = {
		"FaceDataRecord": {
			"faceLibType": FACE_LIB_TYPE,
			"FDID": FDID,
			"FPID": str(emp_no),
		}
	}

	files = {
		"FaceDataRecord": (None, frappe.as_json(face_meta["FaceDataRecord"]), "application/json"),
		"img": ("face.jpg", image_bytes, "image/jpeg"),
	}

	try:
		response = requests.post(url, auth=auth, files=files, verify=False, timeout=30)
		if response.status_code == 200:
			return {"status": "success", "message": f"Face enrolled on {device.device_name}."}
		return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:300]}"}
	except requests.exceptions.RequestException as e:
		return {"status": "error", "message": f"Network error: {e}"}


def _get_employee_image_bytes(employee_doc):
	if not employee_doc.image:
		return None
	file_doc = frappe.get_all("File", filters={"file_url": employee_doc.image}, fields=["name"], limit_page_length=1)
	if not file_doc:
		return None
	f = frappe.get_doc("File", file_doc[0].name)
	return f.get_content()


# ── Pull-from-device + cross-device replication ────────────────────────────
# Workflow: employee enrolls face + fingerprint physically at ONE device
# (the device's own touchscreen / sensor, same as they'd do with HikCentral
# today). ERPNext then pulls that captured data back via ISAPI, stores it
# in "Employee Biometric Template" (ERPNext becomes the source of truth,
# same role HikCentral used to play), and pushes it out to every other
# enabled device.


def _fetch_face_from_device(device, emp_no):
	"""Returns (image_bytes, error_message)."""
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	auth = HTTPDigestAuth(device.username, device.get_password("password"))
	url = f"{base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"
	payload = {
		"UserInfoSearchCond": {
			"searchID": "pull-face",
			"searchResultPosition": 0,
			"maxResults": 1,
			"EmployeeNoList": [{"employeeNo": str(emp_no)}],
		}
	}
	try:
		response = requests.post(url, auth=auth, json=payload, verify=False, timeout=20)
		if response.status_code != 200:
			return None, f"HTTP {response.status_code}"
		data = response.json()
		user_info = data.get("UserInfoSearch", {}).get("UserInfo", [])
		if not user_info:
			return None, "Employee not found on this device."

		face_url = user_info[0].get("faceURL")
		face_data = user_info[0].get("faceData")

		if face_data:
			return base64.b64decode(face_data), None

		if face_url:
			img_response = requests.get(face_url, auth=auth, verify=False, timeout=20)
			if img_response.status_code == 200:
				return img_response.content, None
			return None, f"Face image download failed: HTTP {img_response.status_code}"

		return None, "No face enrolled on this device for this employee."
	except requests.exceptions.RequestException as e:
		return None, f"Network error: {e}"


def _fetch_fingerprint_from_device(device, emp_no, finger_id):
	"""Best-effort fingerprint template pull. ISAPI's fingerprint-download
	endpoint naming/schema varies more across firmware than the face one -
	treat any success here as a bonus, not a guarantee."""
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	auth = HTTPDigestAuth(device.username, device.get_password("password"))
	url = f"{base_url}/ISAPI/AccessControl/FingerPrintUpload?format=json"
	payload = {"FingerPrintCond": {"employeeNo": str(emp_no), "fingerPrintID": finger_id}}
	try:
		response = requests.post(url, auth=auth, json=payload, verify=False, timeout=20)
		if response.status_code != 200:
			return None, f"HTTP {response.status_code} - device/firmware may not support template download over ISAPI."
		data = response.json()
		template = (
			data.get("FingerPrintCfg", {}).get("fingerData")
			or data.get("FingerPrintData", {}).get("fingerData")
		)
		if not template:
			return None, "No fingerprint data returned in a recognized format."
		return template, None
	except requests.exceptions.RequestException as e:
		return None, f"Network error: {e}"
	except ValueError:
		return None, "Device response wasn't valid JSON - fingerprint pull isn't supported here."


@frappe.whitelist()
def pull_and_replicate(employee, source_device, include_face=1, include_fingerprint=1):
	"""Pull whatever was captured at `source_device` and push it to every
	other enabled device. Saves a copy against Employee Biometric Template
	so future new devices can be enrolled without re-visiting the source."""
	frappe.only_for(("System Manager", "HR Manager"))

	employee_doc = frappe.get_doc("Employee", employee)
	emp_no = employee_doc.attendance_device_id
	if not emp_no:
		return {"status": "error", "message": "Set Attendance Device ID on the employee first."}

	device = _device_doc(source_device)
	include_face = int(include_face)
	include_fingerprint = int(include_fingerprint)

	log_lines = []

	if frappe.db.exists("Employee Biometric Template", employee):
		template = frappe.get_doc("Employee Biometric Template", employee)
	else:
		template = frappe.new_doc("Employee Biometric Template")
		template.employee = employee

	template.source_device = source_device
	template.captured_on = frappe.utils.now_datetime()

	if include_face:
		image_bytes, err = _fetch_face_from_device(device, emp_no)
		if image_bytes:
			file_doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"{employee}_face.jpg",
					"attached_to_doctype": "Employee Biometric Template",
					"attached_to_name": employee,
					"attached_to_field": "face_image",
					"content": image_bytes,
					"is_private": 1,
				}
			)
			file_doc.insert(ignore_permissions=True)
			template.face_image = file_doc.file_url
			log_lines.append(f"Face pulled from {device.device_name}.")
		else:
			log_lines.append(f"Face pull failed: {err}")

	if include_fingerprint:
		for finger_id, fieldname in ((1, "fingerprint_1_template"), (2, "fingerprint_2_template")):
			tmpl, err = _fetch_fingerprint_from_device(device, emp_no, finger_id)
			if tmpl:
				template.set(fieldname, tmpl)
				log_lines.append(f"Fingerprint {finger_id} pulled from {device.device_name}.")
			else:
				log_lines.append(f"Fingerprint {finger_id} pull skipped/failed: {err}")

	template.replication_log = "\n".join(log_lines)
	template.save(ignore_permissions=True)
	frappe.db.commit()

	push_result = push_saved_template_to_devices(employee, exclude_device=source_device)

	return {"status": "done", "pull_log": log_lines, "push_result": push_result}


@frappe.whitelist()
def push_saved_template_to_devices(employee, device_name=None, exclude_device=None):
	"""Pushes the stored Employee Biometric Template to one device, or all
	enabled devices except `exclude_device`. Use this whenever a new device
	is added later - no need to re-visit the original enrollment device."""
	frappe.only_for(("System Manager", "HR Manager"))

	if not frappe.db.exists("Employee Biometric Template", employee):
		return {"status": "error", "message": "No saved biometric template for this employee yet - run 'Pull From Device' first."}

	template = frappe.get_doc("Employee Biometric Template", employee)
	employee_doc = frappe.get_doc("Employee", employee)

	targets = [{"name": device_name}] if device_name else _get_devices()
	targets = [t for t in targets if t["name"] != exclude_device]

	results = {}
	for t in targets:
		device = _device_doc(t["name"])
		device_result = {}

		if template.face_image:
			file_doc = frappe.get_all("File", filters={"file_url": template.face_image}, fields=["name"], limit_page_length=1)
			if file_doc:
				image_bytes = frappe.get_doc("File", file_doc[0].name).get_content()
				device_result["face"] = _push_face_to_device(device, employee_doc, image_bytes)

		for finger_id, fieldname in ((1, "fingerprint_1_template"), (2, "fingerprint_2_template")):
			tmpl = template.get(fieldname)
			if tmpl:
				device_result[f"fingerprint_{finger_id}"] = _push_fingerprint_to_device(device, employee_doc, finger_id, tmpl)

		results[device.device_name] = device_result

	return {"status": "done", "results": results}


def _push_fingerprint_to_device(device, employee_doc, finger_id, template_b64):
	"""Best-effort - see module docstring on fingerprint portability."""
	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	auth = HTTPDigestAuth(device.username, device.get_password("password"))
	url = f"{base_url}/ISAPI/AccessControl/FingerPrintDownload?format=json"
	payload = {
		"FingerPrintCfg": {
			"employeeNo": str(employee_doc.attendance_device_id),
			"fingerPrintID": finger_id,
			"fingerData": template_b64,
		}
	}
	try:
		response = requests.put(url, auth=auth, json=payload, verify=False, timeout=20)
		if response.status_code == 200:
			return {"status": "success"}
		return {
			"status": "error",
			"message": (
				f"HTTP {response.status_code} - this device/firmware likely doesn't accept an "
				f"imported template (fingerprint templates aren't always portable across models). "
				f"Manual re-enrollment at this device may be needed."
			),
		}
	except requests.exceptions.RequestException as e:
		return {"status": "error", "message": f"Network error: {e}"}


@frappe.whitelist()
def enroll_face(employee, device_name=None):
	"""Push the Employee's photo (the standard `image` field) to one device,
	or all enabled devices if device_name is omitted."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))

	employee_doc = frappe.get_doc("Employee", employee)
	image_bytes = _get_employee_image_bytes(employee_doc)
	if not image_bytes:
		return {"status": "error", "message": "Employee has no photo uploaded. Capture/upload one first."}
	if not employee_doc.attendance_device_id:
		return {"status": "error", "message": "Set Attendance Device ID on the employee first."}

	targets = [{"name": device_name}] if device_name else _get_devices()
	if not targets:
		return {"status": "error", "message": "No enabled Biometric Device found."}

	results = {}
	for t in targets:
		device = _device_doc(t["name"])
		results[device.device_name] = _push_face_to_device(device, employee_doc, image_bytes)

	return {"status": "done", "results": results}


@frappe.whitelist()
def trigger_fingerprint_capture(employee, device_name):
	"""Experimental / best-effort: asks the device to enter fingerprint
	capture mode for this employeeNo. Behaviour is device/firmware
	dependent - many Hikvision terminals require capture to be started
	from the terminal's own touchscreen or a local USB enrollment reader
	instead. Verify against your device's ISAPI capability document."""
	frappe.only_for(("System Manager", "HR Manager"))

	employee_doc = frappe.get_doc("Employee", employee)
	emp_no = employee_doc.attendance_device_id
	if not emp_no:
		return {"status": "error", "message": "Set Attendance Device ID on the employee first."}

	device = _device_doc(device_name)
	ensured = _ensure_device_user(device, employee_doc)
	if ensured["status"] != "success":
		return ensured

	base_url = f"{device.protocol}://{device.ip}:{device.port}"
	auth = HTTPDigestAuth(device.username, device.get_password("password"))
	url = f"{base_url}/ISAPI/AccessControl/CaptureFingerPrint?format=json"
	payload = {"employeeNo": str(emp_no), "fingerPrintID": 1}

	try:
		response = requests.put(url, auth=auth, json=payload, verify=False, timeout=15)
		if response.status_code == 200:
			return {
				"status": "success",
				"message": "Device notified to start fingerprint capture. Ask the employee to present their finger at the terminal now.",
			}
		return {
			"status": "error",
			"message": (
				f"Device returned HTTP {response.status_code}. This endpoint isn't supported on "
				f"every model/firmware - fingerprint enrollment may need to be done at the terminal "
				f"or with a local USB enrollment reader instead. Details: {response.text[:200]}"
			),
		}
	except requests.exceptions.RequestException as e:
		return {"status": "error", "message": f"Network error: {e}"}


@frappe.whitelist()
def check_enrollment_status(employee):
	"""Looks up whether this employee's device user + face exist on each
	enabled device, using UserInfo/Search."""
	frappe.only_for(("System Manager", "HR Manager", "HR User"))

	employee_doc = frappe.get_doc("Employee", employee)
	emp_no = employee_doc.attendance_device_id
	if not emp_no:
		return {"status": "error", "message": "Set Attendance Device ID on the employee first."}

	results = {}
	for d in _get_devices():
		device = _device_doc(d["name"])
		base_url = f"{device.protocol}://{device.ip}:{device.port}"
		auth = HTTPDigestAuth(device.username, device.get_password("password"))
		url = f"{base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"
		payload = {
			"UserInfoSearchCond": {
				"searchID": "enrollment-check",
				"searchResultPosition": 0,
				"maxResults": 1,
				"EmployeeNoList": [{"employeeNo": str(emp_no)}],
			}
		}
		try:
			response = requests.post(url, auth=auth, json=payload, verify=False, timeout=15)
			if response.status_code != 200:
				results[device.device_name] = {"enrolled": False, "message": f"HTTP {response.status_code}"}
				continue
			data = response.json()
			user_info = data.get("UserInfoSearch", {}).get("UserInfo", [])
			if user_info:
				info = user_info[0]
				results[device.device_name] = {
					"enrolled": True,
					"has_face": bool(info.get("faceURL") or info.get("faceData") or info.get("numOfFace")),
					"name_on_device": info.get("name"),
				}
			else:
				results[device.device_name] = {"enrolled": False}
		except requests.exceptions.RequestException as e:
			results[device.device_name] = {"enrolled": False, "message": f"Network error: {e}"}

	return {"status": "done", "results": results}
