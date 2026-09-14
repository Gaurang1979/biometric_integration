# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Reconciles Daily Movement Log rows into Employee Checkin IN/OUT records.

A day is only reconciled once a Shift Assignment can be resolved for that
employee/date. The window used is: shift start time  ->  shift end time + 12
hours. This means:
  - If HR assigns the Shift on time, near-real-time reconciliation (called
    right after each device sync) creates the checkins immediately.
  - If the Shift Assignment is only added later, the raw punches were already
    safe in Employee Movement, so the next scheduled reconciliation pass
    (reconcile_all_pending) picks them up automatically.

Manual protection: an Employee Checkin is never touched by reconciliation if
it is `custom_entry_type = "Manual"` or `custom_manually_modified = 1`.
"""

import json
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, get_datetime, getdate


def _time_str(value):
	"""Frappe 'Time' fields round-trip as timedelta once a doc is reloaded
	from the DB (they're set as plain 'HH:MM:SS' strings before the first
	save). Normalise either shape to a zero-padded 'HH:MM:SS' string."""
	if isinstance(value, timedelta):
		total_seconds = int(value.total_seconds())
		h, rem = divmod(total_seconds, 3600)
		m, s = divmod(rem, 60)
		return f"{h:02d}:{m:02d}:{s:02d}"
	return str(value)


def _resolve_shift_type(employee, date):
	rows = frappe.db.sql(
		"""
		SELECT shift_type FROM `tabShift Assignment`
		WHERE employee=%(employee)s AND docstatus=1 AND start_date <= %(date)s
		AND (end_date IS NULL OR end_date >= %(date)s)
		ORDER BY start_date DESC LIMIT 1
		""",
		{"employee": employee, "date": date},
		as_dict=True,
	)
	return rows[0].shift_type if rows else None


def _shift_window(employee, date):
	shift_type_name = _resolve_shift_type(employee, date)
	if not shift_type_name:
		return None

	shift_type = frappe.get_cached_doc("Shift Type", shift_type_name)
	start_dt = get_datetime(f"{date} {shift_type.start_time}")
	end_dt = get_datetime(f"{date} {shift_type.end_time}")
	if shift_type.end_time < shift_type.start_time:
		end_dt = add_to_date(end_dt, days=1)  # overnight shift

	window_end = add_to_date(end_dt, hours=12)
	return start_dt, window_end


def _upsert_checkin(employee, dt, log_type, row, fieldname):
	existing_name = row.get(fieldname)
	if existing_name and frappe.db.exists("Employee Checkin", existing_name):
		existing = frappe.get_doc("Employee Checkin", existing_name)
		if existing.get("custom_entry_type") == "Manual" or existing.get("custom_manually_modified"):
			return existing_name  # protected - leave untouched
		frappe.flags.in_biometric_sync = True
		try:
			existing.time = dt
			existing.log_type = log_type
			existing.save(ignore_permissions=True)
		finally:
			frappe.flags.in_biometric_sync = False
		return existing.name

	frappe.flags.in_biometric_sync = True
	try:
		doc = frappe.new_doc("Employee Checkin")
		doc.employee = employee
		doc.time = dt
		doc.log_type = log_type
		doc.custom_entry_type = "Auto"
		doc.custom_original_snapshot = json.dumps({"time": str(dt), "log_type": log_type})
		doc.insert(ignore_permissions=True)
	finally:
		frappe.flags.in_biometric_sync = False
	return doc.name


def reconcile_day(employee, date, row):
	"""Reconcile a single Daily Movement Log row (in place, unsaved)."""
	if not row.first_punch or not row.last_punch:
		return

	window = _shift_window(employee, date)
	if not window:
		row.checkin_status = "Pending Shift"
		return

	window_start, window_end = window
	in_dt = get_datetime(f"{date} {row.first_punch}")
	out_dt = get_datetime(f"{date} {row.last_punch}")

	if not (window_start <= in_dt <= window_end):
		row.checkin_status = "Out of Shift Window"
		return

	row.checkin_ref = _upsert_checkin(employee, in_dt, "IN", row, "checkin_ref")
	if out_dt != in_dt:
		row.checkout_ref = _upsert_checkin(employee, out_dt, "OUT", row, "checkout_ref")
	row.checkin_status = "Reconciled"


@frappe.whitelist()
def reconcile_month(employee, year, month):
	name = f"{employee}-{year}-{month}"
	if not frappe.db.exists("Employee Movement", name):
		return {"status": "not_found"}

	movement = frappe.get_doc("Employee Movement", name)
	for row in movement.daily_logs:
		reconcile_day(movement.employee, getdate(row.date), row)
	movement.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "done"}


def reconcile_all_pending():
	"""Scheduled entry point: re-check every day row that isn't reconciled yet
	(covers shifts assigned after the fact)."""
	pending_parents = frappe.db.sql(
		"""
		SELECT DISTINCT parent FROM `tabDaily Movement Log`
		WHERE IFNULL(checkin_status, '') IN ('', 'Pending Shift')
		""",
		as_dict=True,
	)

	for p in pending_parents:
		movement = frappe.get_doc("Employee Movement", p.parent)
		changed = False
		for row in movement.daily_logs:
			if (row.checkin_status or "Pending Shift") == "Pending Shift":
				reconcile_day(movement.employee, getdate(row.date), row)
				changed = True
		if changed:
			movement.save(ignore_permissions=True)

	frappe.db.commit()
