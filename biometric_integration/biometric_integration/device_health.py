# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
Pings every enabled Biometric Device on a schedule and tracks online/offline
state, plus clock drift vs the ERPNext server. Sends an email alert only on
a state TRANSITION (online->offline, or in-sync->drifted) - not on every
poll - so an ongoing issue doesn't spam recipients every cycle.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone as _tz  # noqa: F401 (timezone kept for clarity/future use)

import frappe
import requests
from requests.auth import HTTPDigestAuth

from biometric_integration.biometric_integration.doctype.biometric_audit_log.biometric_audit_log import log_action


def _ping(device):
	try:
		url = f"{device.protocol}://{device.ip}:{device.port}/ISAPI/System/deviceInfo"
		auth = HTTPDigestAuth(device.username, device.get_password("password"))
		response = requests.get(url, auth=auth, timeout=8, verify=False)
		return response.status_code == 200
	except requests.exceptions.RequestException:
		return False


def _get_device_time(device):
	"""Returns (device_datetime_utc, error) via ISAPI /ISAPI/System/time."""
	try:
		url = f"{device.protocol}://{device.ip}:{device.port}/ISAPI/System/time"
		auth = HTTPDigestAuth(device.username, device.get_password("password"))
		response = requests.get(url, auth=auth, timeout=8, verify=False)
		if response.status_code != 200:
			return None, f"HTTP {response.status_code}"

		root = ET.fromstring(response.content)
		ns = {"ns": "http://www.isapi.org/ver20/XMLSchema"}
		local_time_el = root.find("ns:localTime", ns)
		if local_time_el is None or not local_time_el.text:
			return None, "No localTime in device response"

		# e.g. "2026-09-11T18:05:33+05:30"
		raw = local_time_el.text
		match = re.match(r"^(.*T[\d:]+)([+-]\d{2}:\d{2})$", raw)
		if not match:
			return None, f"Unrecognized time format: {raw}"

		dt = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
		offset_str = match.group(2)
		sign = 1 if offset_str[0] == "+" else -1
		oh, om = offset_str[1:].split(":")
		offset_minutes = sign * (int(oh) * 60 + int(om))
		dt_utc = dt - timedelta(minutes=offset_minutes)
		return dt_utc, None
	except requests.exceptions.RequestException as e:
		return None, f"Network error: {e}"
	except Exception as e:
		return None, f"Could not parse device time: {e}"


def _alert_offline(device):
	settings = frappe.get_single("Biometric Integration Settings")
	recipients = [r.strip() for r in (settings.device_offline_alert_recipients or "").split(",") if r.strip()]
	if not recipients:
		return
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=f"[Biometric Integration] Device offline: {device.device_name}",
			message=(
				f"<p>Device <b>{device.device_name}</b> ({device.ip}) stopped responding as of "
				f"{frappe.utils.now_datetime()}.</p>"
				f"<p>Attendance and access control on this device are unavailable until it's back online.</p>"
			),
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Device Offline Alert Email Failed")


def _alert_drift(device, drift_seconds):
	settings = frappe.get_single("Biometric Integration Settings")
	recipients = [r.strip() for r in (settings.device_offline_alert_recipients or "").split(",") if r.strip()]
	if not recipients:
		return
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=f"[Biometric Integration] Clock drift on {device.device_name}",
			message=(
				f"<p>Device <b>{device.device_name}</b> ({device.ip}) clock is off from the server "
				f"by approximately {drift_seconds:.0f} seconds.</p>"
				f"<p>Large drift can throw off event ordering and the anti-passback cooldown window. "
				f"Sync the device's time (NTP, or manually) when convenient.</p>"
			),
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Clock Drift Alert Email Failed")


@frappe.whitelist()
def check_all_devices():
	settings = frappe.get_single("Biometric Integration Settings")
	max_drift = settings.max_clock_drift_seconds or 120

	devices = frappe.get_all(
		"Biometric Device",
		filters={"enabled": 1},
		fields=["name", "device_name", "ip", "port", "protocol", "username", "is_online"],
	)

	results = {}
	for d in devices:
		device = frappe.get_doc("Biometric Device", d.name)
		is_online_now = _ping(device)
		was_online = bool(d.is_online)

		updates = {"is_online": 1 if is_online_now else 0}
		if is_online_now:
			updates["last_seen_online"] = frappe.utils.now_datetime()

		drift_seconds = None
		if is_online_now:
			device_time_utc, err = _get_device_time(device)
			if device_time_utc:
				drift_seconds = (device_time_utc - datetime.utcnow()).total_seconds()
				updates["clock_drift_seconds"] = drift_seconds
				was_in_sync = frappe.db.get_value("Biometric Device", d.name, "time_sync_ok")
				is_in_sync = abs(drift_seconds) <= max_drift
				updates["time_sync_ok"] = 1 if is_in_sync else 0
				if was_in_sync and not is_in_sync:
					_alert_drift(device, drift_seconds)
					log_action("Device Sync", "Failed", device=d.name, details=f"Clock drift {drift_seconds:.0f}s exceeds {max_drift}s threshold.")

		frappe.db.set_value("Biometric Device", d.name, updates)
		results[d.device_name] = {
			"status": "online" if is_online_now else "offline",
			"drift_seconds": drift_seconds,
		}

		if was_online and not is_online_now:
			_alert_offline(device)
			log_action("Device Sync", "Failed", device=d.name, details="Device went offline.")

	frappe.db.commit()
	return results
