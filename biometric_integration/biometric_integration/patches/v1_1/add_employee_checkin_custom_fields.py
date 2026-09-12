# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Employee Checkin": [
				{
					"fieldname": "biometric_event_id",
					"fieldtype": "Data",
					"label": "Biometric Event ID",
					"insert_after": "device_id",
					"unique": 1,
					"hidden": 1,
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "biometric_manual_punch",
					"fieldtype": "Data",
					"label": "Source Manual Punch",
					"insert_after": "biometric_event_id",
					"hidden": 1,
					"read_only": 1,
					"no_copy": 1,
				},
			]
		},
		ignore_validate=frappe.flags.in_patch,
	)
