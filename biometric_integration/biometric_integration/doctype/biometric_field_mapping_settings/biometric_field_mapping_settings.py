# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BiometricFieldMappingSettings(Document):
	pass


def get_mapping_rows(target_system, direction=None):
	"""Return enabled mapping rows for a target system, optionally filtered by direction."""
	settings = frappe.get_single("Biometric Field Mapping Settings")
	rows = [
		row
		for row in settings.field_mapping
		if row.enabled and row.target_system == target_system
	]
	if direction:
		rows = [row for row in rows if row.sync_direction in (direction, "Both")]
	return rows
