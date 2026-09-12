# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BiometricAuditLog(Document):
	pass


def log_action(action, status, employee=None, device=None, details=None):
	"""Fire-and-forget audit entry. Never raises - a broken audit log
	shouldn't block the actual enroll/revoke/sync action."""
	try:
		frappe.get_doc(
			{
				"doctype": "Biometric Audit Log",
				"employee": employee,
				"device": device,
				"action": action,
				"status": status,
				"performed_by": frappe.session.user,
				"timestamp": frappe.utils.now_datetime(),
				"details": (details or "")[:900],
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Biometric Audit Log Write Failed")
