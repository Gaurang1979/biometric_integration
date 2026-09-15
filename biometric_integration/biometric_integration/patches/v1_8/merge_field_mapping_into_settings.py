# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""
"Biometric Field Mapping Settings" (a Single) is retired - its fields are
now the "Field Mapping" tab on Biometric Integration Settings (same move as
Devices before it, see v1_6). Runs post_model_sync so the target fields
already exist on Biometric Integration Settings to write into.
"""

import frappe

SINGLE_VALUE_FIELDS = (
	"enable_employee_push_to_mobile",
	"mobile_employee_webhook_url",
	"enable_employee_push_to_devices",
	"enable_device_access_control",
)


def execute():
	if not frappe.db.exists("DocType", "Biometric Field Mapping Settings"):
		return

	for fieldname in SINGLE_VALUE_FIELDS:
		value = frappe.db.get_single_value("Biometric Field Mapping Settings", fieldname)
		if value:
			frappe.db.set_single_value("Biometric Integration Settings", fieldname, value)

	if frappe.db.table_exists("Biometric Field Mapping Row"):
		frappe.db.sql(
			"""
			UPDATE `tabBiometric Field Mapping Row`
			SET parent = 'Biometric Integration Settings',
			    parenttype = 'Biometric Integration Settings'
			WHERE parent = 'Biometric Field Mapping Settings'
			"""
		)

	frappe.delete_doc("DocType", "Biometric Field Mapping Settings", force=True, ignore_permissions=True)
	frappe.db.commit()
	frappe.logger().info("biometric_integration: merged Biometric Field Mapping Settings into Biometric Integration Settings.")
