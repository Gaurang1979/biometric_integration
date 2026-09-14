# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Employee Movement helpers.

Every raw biometric/mobile punch is recorded here first, into one
"Employee Movement" document per employee per calendar month, with one
child "Daily Movement Log" row per day holding the full punch trail plus
daily total-in / total-out minutes.

This is intentionally separate from Employee Checkin: Employee Checkin only
ever gets the *reconciled* first/last punch of the day (see reconciliation.py),
so it stays clean for Shift/Attendance/Payroll to consume, while this module
keeps the full raw trail for audit and for late reconciliation once a Shift
Assignment is added.
"""

import frappe
from frappe.utils import get_time, get_datetime


def _movement_name(employee, date):
	return f"{employee}-{date.year}-{date.month}"


def get_or_create_movement(employee, date):
	name = _movement_name(employee, date)
	if frappe.db.exists("Employee Movement", name):
		return frappe.get_doc("Employee Movement", name)

	doc = frappe.new_doc("Employee Movement")
	doc.employee = employee
	doc.year = date.year
	doc.month = date.month
	doc.insert(ignore_permissions=True)
	return doc


def _parse_punch_log(punch_log):
	return [p.strip() for p in (punch_log or "").split(",") if p.strip()]


def _to_minutes(time_str):
	t = get_time(time_str)
	return t.hour * 60 + t.minute + t.second / 60


def _compute_in_out_minutes(punch_times):
	"""Punches are assumed to alternate IN, OUT, IN, OUT... (odd index = OUT).
	total_in  = time spent between an IN and the following OUT (presence)
	total_out = time spent between an OUT and the following IN (away/break)
	An unmatched trailing punch (odd count) is left out of both totals.
	"""
	mins = [_to_minutes(t) for t in punch_times]
	total_in = 0.0
	total_out = 0.0
	for i in range(0, len(mins) - 1, 2):
		total_in += max(mins[i + 1] - mins[i], 0)
	for i in range(1, len(mins) - 1, 2):
		total_out += max(mins[i + 1] - mins[i], 0)
	return round(total_in), round(total_out)


def add_punch(employee, event_dt, device_name=None):
	"""Append one raw punch to the employee's monthly movement log.
	Returns (movement_doc, daily_log_row, is_new). is_new is False when this
	exact employee/date/time was already recorded (re-polled duplicate) -
	nothing is written in that case.
	"""
	event_dt = get_datetime(event_dt)
	date = event_dt.date()
	time_str = event_dt.strftime("%H:%M:%S")

	movement = get_or_create_movement(employee, date)

	row = None
	for r in movement.daily_logs:
		if str(r.date) == str(date):
			row = r
			break
	if row is None:
		row = movement.append("daily_logs", {"date": date})

	punches = _parse_punch_log(row.punch_log)
	if time_str in punches:
		return movement, row, False

	punches.append(time_str)
	punches.sort()

	row.punch_log = ", ".join(punches)
	row.punch_count = len(punches)
	row.first_punch = punches[0]
	row.last_punch = punches[-1]
	row.total_in_minutes, row.total_out_minutes = _compute_in_out_minutes(punches)

	movement.save(ignore_permissions=True)

	# re-fetch the row from the saved doc so callers get current child idx/name
	for r in movement.daily_logs:
		if str(r.date) == str(date):
			return movement, r, True
	return movement, row, True


def delete_old_movements():
	"""Delete Employee Movement records based on Biometric Integration Settings,
	mirroring the retention behaviour the old Biometric Attendance Log had."""
	settings = frappe.get_single("Biometric Integration Settings")
	if not settings.get("enable_biometric_attendance_log_deletion"):
		return

	retention_days = settings.get("delete_logs_after_days") or 370
	from frappe.utils import add_days, today, getdate

	cutoff = getdate(add_days(today(), -retention_days))

	old = frappe.get_all(
		"Employee Movement",
		filters={"year": ["<", cutoff.year]},
		pluck="name",
	)
	# also catch the current-year-but-earlier-month case
	old += frappe.get_all(
		"Employee Movement",
		filters={"year": cutoff.year, "month": ["<", cutoff.month]},
		pluck="name",
	)

	for name in set(old):
		frappe.delete_doc("Employee Movement", name, ignore_permissions=True, force=True)

	if old:
		frappe.db.commit()
		frappe.logger().info(f"Deleted {len(set(old))} Employee Movement records older than {retention_days} days")
