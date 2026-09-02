import frappe
from frappe.model.document import Document


class DailyEmployeeMovementLog(Document):
    def before_save(self):
        if self.employee:
            self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name") or ""
