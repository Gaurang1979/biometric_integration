# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime


class BiometricVisitor(Document):
	def validate(self):
		if self.valid_from and self.valid_to and get_datetime(self.valid_to) <= get_datetime(self.valid_from):
			frappe.throw("Valid To must be after Valid From.")

		if frappe.db.exists("Employee", {"attendance_device_id": self.visitor_code}):
			frappe.throw(
				f"Visitor Code '{self.visitor_code}' is already used as an Employee's Attendance Device ID. "
				f"Choose a different code to avoid colliding with an employee on the devices."
			)
