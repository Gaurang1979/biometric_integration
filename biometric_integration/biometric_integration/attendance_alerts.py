# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Late-arrival alerts. Runs every 15 minutes; for each employee with a shift
starting in the last (grace + a small trailing window), checks whether an
Employee Checkin (log_type=IN) already exists for today. If not, emails
the employee's "Reports To" manager (falling back to configured recipients)
- once per employee per day, tracked via Biometric Late Alert Log.

Uses HRMS's "Shift Assignment" doctype for today's shift if that doctype
is installed (more accurate - handles shift changes/rotations), otherwise
falls back to Employee.default_shift so this still works on plain ERPNext
HR without the separate HRMS app's shift-assignment feature.
"""

import frappe
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime, nowtime

from biometric_integration.biometric_integration.doctype.biometric_audit_log.biometric_audit_log import log_action

# How far past (start + grace) we still consider "worth alerting on" - avoids
# firing a stale alert hours later for someone who took the day off without
# a leave record, once the window has clearly passed.
TRAILING_WINDOW_MINUTES = 45


def _todays_shift_start(employee_name, default_shift):
	if frappe.db.exists("DocType", "Shift Assignment"):
		assignment = frappe.db.get_value(
			"Shift Assignment",
			{"employee": employee_name, "start_date": ["<=", getdate()], "docstatus": 1},
			["shift_type"],
			order_by="start_date desc",
		)
		shift_type = assignment
	else:
		shift_type = default_shift

	if not shift_type:
		return None
	return frappe.db.get_value("Shift Type", shift_type, "start_time")


@frappe.whitelist()
def check_late_arrivals():
	settings = frappe.get_single("Biometric Integration Settings")
	if not settings.enable_late_arrival_alerts:
		return {"status": "disabled"}

	grace = settings.late_arrival_grace_minutes or 0
	fallback_recipients = [
		r.strip() for r in (settings.late_arrival_fallback_recipients or "").split(",") if r.strip()
	]

	today = getdate()
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "employee_name", "default_shift", "reports_to"],
	)

	alerted = []
	for emp in employees:
		start_time = _todays_shift_start(emp.name, emp.default_shift)
		if not start_time:
			continue

		shift_start_dt = get_datetime(f"{today} {start_time}")
		alert_after = add_to_date(shift_start_dt, minutes=grace)
		alert_window_end = add_to_date(alert_after, minutes=TRAILING_WINDOW_MINUTES)

		now = now_datetime()
		if not (alert_after <= now <= alert_window_end):
			continue

		if frappe.db.exists("Biometric Late Alert Log", {"employee": emp.name, "alert_date": today}):
			continue

		has_checkin = frappe.db.exists(
			"Employee Checkin",
			{"employee": emp.name, "log_type": "IN", "time": [">=", f"{today} 00:00:00"]},
		)
		if has_checkin:
			continue

		recipients = fallback_recipients[:]
		if emp.reports_to:
			manager_email = frappe.db.get_value("Employee", emp.reports_to, "user_id")
			if manager_email:
				recipients.append(manager_email)

		if not recipients:
			continue

		try:
			frappe.sendmail(
				recipients=recipients,
				subject=f"[Biometric Integration] Late arrival: {emp.employee_name}",
				message=(
					f"<p>{emp.employee_name} has not checked in yet. Shift was due to start at "
					f"{start_time} (grace period {grace} min).</p>"
				),
			)
			frappe.get_doc(
				{
					"doctype": "Biometric Late Alert Log",
					"employee": emp.name,
					"alert_date": today,
					"alerted_at": now,
					"recipient": ", ".join(recipients),
				}
			).insert(ignore_permissions=True)
			log_action("Late Arrival Alert", "Success", employee=emp.name, details=f"Alerted: {', '.join(recipients)}")
			alerted.append(emp.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Late Arrival Alert Email Failed")

	frappe.db.commit()
	return {"status": "done", "alerted": alerted}
