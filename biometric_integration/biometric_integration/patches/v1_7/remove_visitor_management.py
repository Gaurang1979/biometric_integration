# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""Visitor Management (previously the "Biometric Visitor" doctype, briefly
renamed to "Visitor Registration" in a since-reverted change) is removed
entirely - this module is scoped purely to employee attendance/movement.
Handles the doctype existing under either name, whichever state a given
site's earlier migrate left it in."""

import frappe


def execute():
	for doctype in ("Visitor Registration", "Biometric Visitor"):
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
	frappe.db.commit()
