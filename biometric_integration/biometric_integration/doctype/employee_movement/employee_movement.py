# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import calendar

import frappe
from frappe.model.document import Document


class EmployeeMovement(Document):
	def validate(self):
		self.month_name = calendar.month_name[int(self.month)] if self.month else ""
		self.total_days_logged = len(self.daily_logs or [])
