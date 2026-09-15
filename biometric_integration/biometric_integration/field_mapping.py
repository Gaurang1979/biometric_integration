# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""Field mapping rows moved here (2026-09-15) from the retired standalone
"Biometric Field Mapping Settings" singleton - now just the "Field Mapping"
tab on Biometric Integration Settings, same as Devices before it."""

import frappe


def get_mapping_rows(target_system, direction=None):
	"""Return enabled mapping rows for a target system, optionally filtered by direction."""
	settings = frappe.get_single("Biometric Integration Settings")
	rows = [
		row
		for row in settings.field_mapping
		if row.enabled and row.target_system == target_system
	]
	if direction:
		rows = [row for row in rows if row.sync_direction in (direction, "Both")]
	return rows
