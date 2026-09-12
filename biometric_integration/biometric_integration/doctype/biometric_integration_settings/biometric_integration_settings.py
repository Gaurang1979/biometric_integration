# Copyright (c) 2025, NDV and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BiometricIntegrationSettings(Document):
	"""Global, non-device-specific settings only.

	Device connections: see Biometric Device (one record per Hikvision device).
	Field mapping to devices / mobile app: see Biometric Field Mapping Settings.
	Sync logic: see device_sync.py (devices) and mobile_api.py (mobile app).
	"""

	pass
