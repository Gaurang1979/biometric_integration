# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Employee Checkin": [
				{
					"fieldname": "flagged_anti_passback",
					"fieldtype": "Check",
					"label": "Flagged (Anti-Passback)",
					"insert_after": "biometric_manual_punch",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "flag_reason",
					"fieldtype": "Small Text",
					"label": "Flag Reason",
					"insert_after": "flagged_anti_passback",
					"read_only": 1,
					"no_copy": 1,
				},
			]
		},
		ignore_validate=frappe.flags.in_patch,
	)
