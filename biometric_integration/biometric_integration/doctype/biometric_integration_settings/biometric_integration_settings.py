# Copyright (c) 2025, NDV and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BiometricIntegrationSettings(Document):
	"""Single doctype, everything under one roof across three tabs:
	General (retention/alerts/anti-passback/late-arrival), Devices (one row
	per Hikvision device), and Field Mapping (ERPNext <-> device/mobile app
	field mapping). Sync logic: see device_sync.py (devices) and
	mobile_api.py (mobile app).
	"""

	pass
