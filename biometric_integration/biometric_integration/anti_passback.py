# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Anti-passback DETECTION, not real-time blocking.

Important limitation, stated plainly: devices are polled every 15 minutes
(see device_sync.py), so by the time ERPNext sees an event the door has
already opened. This cannot stop a tailgating/shared-badge attempt as it
happens - it flags the resulting Employee Checkin and can alert a human,
which is what's actually achievable with a polling architecture. True
real-time blocking would require the device to push events to ERPNext
instantly (most standalone Hikvision terminals don't do this without
HikCentral or custom firmware) and ERPNext (or the device itself) to hold
its own door-open decision, which is a materially different system.
"""

import frappe
from frappe.utils import add_to_date, get_datetime

from biometric_integration.biometric_integration.doctype.biometric_audit_log.biometric_audit_log import log_action


def check_and_flag(employee, device_name, event_dt, checkin_name):
	settings = frappe.get_single("Biometric Integration Settings")
	cooldown = settings.anti_passback_cooldown_minutes
	if not cooldown:
		return

	window_start = add_to_date(get_datetime(event_dt), minutes=-cooldown)
	window_end = add_to_date(get_datetime(event_dt), minutes=cooldown)

	recent = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"name": ["!=", checkin_name],
			"time": ["between", [window_start, window_end]],
		},
		fields=["name", "device_id", "time"],
		order_by="time desc",
		limit_page_length=5,
	)

	conflicting = [r for r in recent if r.device_id and r.device_id != device_name]
	if not conflicting:
		return

	other = conflicting[0]
	reason = (
		f"Checked in at '{device_name}' at {event_dt}, within {cooldown} min of a checkin "
		f"at '{other.device_id}' ({other.time}). Possible shared badge / tailgating - verify manually."
	)

	frappe.db.set_value(
		"Employee Checkin", checkin_name, {"flagged_anti_passback": 1, "flag_reason": reason}
	)
	frappe.db.commit()

	log_action("Anti-Passback Flag", "Failed", employee=employee, device=device_name, details=reason)

	recipients = [r.strip() for r in (settings.anti_passback_alert_recipients or "").split(",") if r.strip()]
	if recipients:
		try:
			frappe.sendmail(
				recipients=recipients,
				subject=f"[Biometric Integration] Possible anti-passback event: {employee}",
				message=f"<p>{reason}</p>",
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Anti-Passback Alert Email Failed")
