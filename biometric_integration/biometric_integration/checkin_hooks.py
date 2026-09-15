# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Hooked onto HRMS's Employee Checkin (see hooks.py doc_events).

Marks every Checkin as Auto (system) or Manual (created by a person in Desk),
and flags Auto records that a person later hand-edits, so reconciliation.py
never silently overwrites a human's correction - and so the form/list can
highlight those in red (see public/js/employee_checkin.js).
"""

import json

import frappe


def before_insert(doc, method=None):
	if frappe.db.exists("Employee Checkin", {"employee": doc.employee, "time": doc.time}):
		frappe.throw(
			f"A Checkin already exists for {doc.employee} at {doc.time}.",
			title="Duplicate Checkin",
		)

	if not doc.get("custom_entry_type"):
		# Our own sync/reconciliation code always sets this explicitly before
		# insert; anything left blank was created directly by a Desk user -
		# this also covers what used to be the separate "Biometric Manual
		# Punch" wizard doctype, since that just called Employee Checkin's
		# own insert() without setting this field either.
		doc.custom_entry_type = "Manual"

	if doc.custom_entry_type == "Auto" and not doc.get("custom_original_snapshot"):
		doc.custom_original_snapshot = json.dumps({"time": str(doc.time), "log_type": doc.log_type})


def on_update(doc, method=None):
	if frappe.flags.get("in_biometric_sync"):
		return  # this save came from our own sync/reconciliation code
	if doc.get("custom_entry_type") != "Auto":
		return
	if doc.get("custom_manually_modified"):
		return

	try:
		original = json.loads(doc.get("custom_original_snapshot") or "{}")
	except Exception:
		original = {}
	if not original:
		return

	if str(doc.time) != original.get("time") or doc.log_type != original.get("log_type"):
		frappe.db.set_value(
			"Employee Checkin", doc.name, "custom_manually_modified", 1, update_modified=False
		)
