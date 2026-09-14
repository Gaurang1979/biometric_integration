# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
"Biometric Attendance Log" / "Biometric Attendance Punch Table" are retired -
replaced by "Employee Movement" / "Daily Movement Log" (see movement.py).

Best-effort data carry-over for anyone who had records in the old doctype
(device_sync.py never wrote to it - it always wrote straight to Employee
Checkin - so on most sites this will find nothing to migrate, which is
fine). Runs post_model_sync so the new Employee Movement table already
exists to insert into.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Biometric Attendance Log"):
		_cleanup_old_doctypes()
		return

	from biometric_integration.biometric_integration.movement import get_or_create_movement

	old_logs = frappe.get_all(
		"Biometric Attendance Log",
		fields=["name", "employee_no", "event_date"],
	)

	for log in old_logs:
		employee = frappe.db.get_value("Employee", {"attendance_device_id": log.employee_no}, "name") or (
			log.employee_no if frappe.db.exists("Employee", log.employee_no) else None
		)
		if not employee or not log.event_date:
			continue

		punches = frappe.get_all(
			"Biometric Attendance Punch Table",
			filters={"parent": log.name},
			fields=["punch_time"],
			order_by="punch_time",
		)
		if not punches:
			continue

		movement = get_or_create_movement(employee, log.event_date)
		row = next((r for r in movement.daily_logs if str(r.date) == str(log.event_date)), None)
		if row:
			continue  # already has data for this date, don't clobber

		times = [str(p.punch_time) for p in punches]
		row = movement.append("daily_logs", {"date": log.event_date})
		row.punch_log = ", ".join(times)
		row.punch_count = len(times)
		row.first_punch = times[0]
		row.last_punch = times[-1]
		movement.save(ignore_permissions=True)

	frappe.db.commit()
	_cleanup_old_doctypes()


def _cleanup_old_doctypes():
	for doctype in ("Biometric Attendance Log", "Biometric Attendance Punch Table"):
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
	frappe.db.commit()
