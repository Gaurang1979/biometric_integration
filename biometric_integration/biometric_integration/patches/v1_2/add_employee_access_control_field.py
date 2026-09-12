# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Employee": [
				{
					"fieldname": "biometric_access_tab",
					"fieldtype": "Tab Break",
					"label": "Biometric Access",
					"insert_after": "attendance_device_id",
				},
				{
					"fieldname": "biometric_access",
					"fieldtype": "Table",
					"label": "Device / Location Access Rules",
					"options": "Employee Biometric Access Row",
					"insert_after": "biometric_access_tab",
					"description": (
						"Leave empty for unrestricted access (enrolled on every enabled device, "
						"the default/legacy behaviour). Add rows to restrict this employee to "
						"specific devices or locations."
					),
				},
			]
		},
		ignore_validate=frappe.flags.in_patch,
	)
