# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
"Biometric Device" is now a child table (istable=1) living on the "Devices"
tab of Biometric Integration Settings, instead of its own standalone list.

Runs post_model_sync, once the schema sync has already added the
parent/parenttype/parentfield/idx columns to `tabBiometric Device` (and
created the Settings `devices` Table field). Any pre-existing device rows
(including one that v1_1's legacy-settings patch may have just inserted
earlier in this same migrate) will have those columns NULL - "adopt" them
onto the Settings singleton so no device configuration is lost, and no
device shows up twice if this patch ever runs again.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Biometric Device"):
		return
	if not frappe.db.has_column("Biometric Device", "parent"):
		return  # schema sync hasn't run yet / already non-child - nothing to adopt

	orphans = frappe.get_all(
		"Biometric Device",
		filters={"parent": ["in", ["", None]]},
		pluck="name",
		order_by="creation asc",
	)
	if not orphans:
		return

	max_idx = frappe.db.sql(
		"""SELECT COALESCE(MAX(idx), 0) FROM `tabBiometric Device`
		   WHERE parent='Biometric Integration Settings'"""
	)[0][0]

	for i, name in enumerate(orphans, start=1):
		frappe.db.set_value(
			"Biometric Device",
			name,
			{
				"parent": "Biometric Integration Settings",
				"parenttype": "Biometric Integration Settings",
				"parentfield": "devices",
				"idx": max_idx + i,
			},
			update_modified=False,
		)

	frappe.db.commit()
	frappe.logger().info(f"biometric_integration: adopted {len(orphans)} device(s) into Biometric Integration Settings.")
