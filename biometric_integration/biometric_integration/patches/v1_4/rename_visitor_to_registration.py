# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Biometric Visitor -> Visitor Registration, moved from the Biometric
	Integration module into its own Visitor Management module."""
	if frappe.db.exists("DocType", "Biometric Visitor") and not frappe.db.exists(
		"DocType", "Visitor Registration"
	):
		frappe.rename_doc("DocType", "Biometric Visitor", "Visitor Registration", force=True)
		frappe.reload_doctype("Visitor Registration", force=True)
