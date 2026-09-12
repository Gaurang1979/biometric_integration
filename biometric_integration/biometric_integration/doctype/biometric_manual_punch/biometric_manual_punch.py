# Copyright (c) 2025, NDV and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe.model.document import Document

from biometric_integration.biometric_integration.doctype.biometric_audit_log.biometric_audit_log import log_action

MANUAL_DEVICE_ID = "Manual Entry"


class BiometricManualPunch(Document):
	def after_insert(self):
		add_manual_punch(self.employee, self.punch_date, self.punch_time, self.name)

	def on_trash(self):
		delete_manual_punch(self)


def _determine_log_type(employee, punch_datetime):
	previous = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["<", punch_datetime]},
		fields=["log_type"],
		order_by="time desc",
		limit_page_length=1,
	)
	if not previous:
		return "IN"
	return "OUT" if previous[0].log_type == "IN" else "IN"


@frappe.whitelist()
def add_manual_punch(employee, punch_date, punch_time, manual_punch_name=None):
	"""Creates the Employee Checkin directly - Manual Punch is now just the UI
	for entering it, not a separate storage doctype."""
	try:
		if isinstance(punch_time, str):
			punch_time = punch_time.split(".")[0]
		punch_datetime = datetime.strptime(f"{punch_date} {punch_time}", "%Y-%m-%d %H:%M:%S")

		if frappe.db.exists(
			"Employee Checkin",
			{"employee": employee, "time": punch_datetime},
		):
			return {"status": "error", "message": "A checkin already exists for this employee at this exact time."}

		doc = frappe.new_doc("Employee Checkin")
		doc.employee = employee
		doc.time = punch_datetime
		doc.log_type = _determine_log_type(employee, punch_datetime)
		doc.device_id = MANUAL_DEVICE_ID
		if manual_punch_name and hasattr(doc, "biometric_manual_punch"):
			doc.biometric_manual_punch = manual_punch_name
		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		log_action("Manual Punch", "Success", employee=employee, details=f"{punch_datetime} ({doc.log_type})")
		return {"status": "success", "message": f"Manual punch recorded as Employee Checkin {doc.name}."}
	except Exception as e:
		return {"status": "error", "message": f"Error adding manual punch: {e}"}


@frappe.whitelist()
def edit_manual_punch(doc_name, new_punch_date, new_punch_time):
	"""Replaces the old edit_button_delete_punch(): removes the Employee Checkin
	created for the previous date/time and re-creates it at the new one."""
	try:
		doc = frappe.get_doc("Biometric Manual Punch", doc_name)
		delete_manual_punch(doc)

		frappe.db.set_value(
			"Biometric Manual Punch", doc_name, {"punch_date": new_punch_date, "punch_time": new_punch_time}
		)
		frappe.db.commit()

		return add_manual_punch(doc.employee, new_punch_date, new_punch_time, doc_name)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Edit Manual Punch Error")
		return {"status": "error", "message": str(e)}


def delete_manual_punch(doc, method=None):
	"""Hooked from Biometric Manual Punch on_trash: remove the matching Employee Checkin."""
	try:
		name = doc.get("name") if hasattr(doc, "get") else doc.name
		checkins = frappe.get_all(
			"Employee Checkin",
			filters={"biometric_manual_punch": name} if frappe.db.has_column("Employee Checkin", "biometric_manual_punch")
			else {"employee": doc.get("employee"), "device_id": MANUAL_DEVICE_ID},
			pluck="name",
		)
		for checkin_name in checkins:
			frappe.delete_doc("Employee Checkin", checkin_name, ignore_permissions=True, force=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Delete Manual Punch Checkin Error")
