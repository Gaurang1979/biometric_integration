# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""Custom fields added onto HRMS's Employee Checkin. Called from
after_migrate (see hooks.py) - create_custom_fields is idempotent (update=True)
so this is safe to run on every migrate."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

EMPLOYEE_CHECKIN_CUSTOM_FIELDS = {
	"Employee Checkin": [
		{
			"fieldname": "custom_biometric_section",
			"fieldtype": "Section Break",
			"label": "Biometric Integration",
			"insert_after": "log_type",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_entry_type",
			"fieldtype": "Select",
			"label": "Entry Type",
			"options": "\nAuto\nManual",
			"insert_after": "custom_biometric_section",
			"read_only": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_manually_modified",
			"fieldtype": "Check",
			"label": "Manually Modified",
			"insert_after": "custom_entry_type",
			"read_only": 1,
			"in_list_view": 1,
		},
		{
			"fieldname": "custom_column_break_cin1",
			"fieldtype": "Column Break",
			"insert_after": "custom_manually_modified",
		},
		{
			"fieldname": "custom_movement_reference",
			"fieldtype": "Link",
			"label": "Employee Movement",
			"options": "Employee Movement",
			"insert_after": "custom_column_break_cin1",
			"read_only": 1,
		},
		{
			"fieldname": "custom_original_snapshot",
			"fieldtype": "Small Text",
			"label": "Original Snapshot (system use)",
			"insert_after": "custom_movement_reference",
			"read_only": 1,
			"hidden": 1,
		},
	]
}


def create_biometric_custom_fields():
	create_custom_fields(EMPLOYEE_CHECKIN_CUSTOM_FIELDS, update=True)
