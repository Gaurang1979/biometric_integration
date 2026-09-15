# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
"Biometric Manual Punch" is retired - it was already just a thin UI wrapper
that inserted a plain Employee Checkin (its own docstring said so). Now that
checkin_hooks.py auto-detects and protects manual entries on Employee
Checkin directly, the wrapper doctype adds nothing standard Employee
Checkin can't already do.

Backfills custom_entry_type='Manual' on any existing Employee Checkin that
predates checkin_hooks.py (so old manually-entered records still get
flagged/protected/highlighted), then removes the wrapper doctype.
"""

import frappe


def execute():
	if frappe.db.has_column("Employee Checkin", "custom_entry_type"):
		frappe.db.sql(
			"""
			UPDATE `tabEmployee Checkin`
			SET custom_entry_type = 'Manual'
			WHERE IFNULL(custom_entry_type, '') = ''
			"""
		)

	if frappe.db.exists("DocType", "Biometric Manual Punch"):
		frappe.delete_doc("DocType", "Biometric Manual Punch", force=True, ignore_permissions=True)

	frappe.db.commit()
