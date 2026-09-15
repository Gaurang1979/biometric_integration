# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""Rewritten 2026-09-14 to read straight from ERPNext's standard "Leave
Application" doctype instead of the retired custom "Biometric Leave Log"
(which nothing in this app ever wrote to). Note: standard Leave Application
only models whole/half-day leave, not an arbitrary clock-time window, so the
old "Leave From"/"Leave To" clock-time columns are no longer available -
Half Day is shown instead."""

import calendar
from datetime import datetime

import frappe
from frappe import _


def execute(filters=None):
	columns = [
		{"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 250, "align": "left"},
		{"fieldname": "employee_id", "label": _("ID"), "fieldtype": "Data", "width": 80, "align": "center"},
		{"fieldname": "leave_type", "label": _("Leave Type"), "fieldtype": "Data", "width": 150, "align": "left"},
		{"fieldname": "full_day", "label": _("Full Day"), "fieldtype": "Data", "width": 80, "align": "center"},
	]

	selected_date = filters.get("date") if filters else None
	selected_emp = filters.get("employee") if filters else None
	selected_month = filters.get("month") if filters else None
	selected_year = filters.get("year") if filters else None

	if not selected_date and not (selected_emp and selected_month and selected_year):
		return columns, []

	if selected_emp and selected_month and selected_year:
		month_dt = datetime.strptime(f"{selected_month} {selected_year}", "%B %Y")
		first_day = month_dt.replace(day=1).strftime("%Y-%m-%d")
		last_day = month_dt.replace(
			day=calendar.monthrange(month_dt.year, month_dt.month)[1]
		).strftime("%Y-%m-%d")

		columns[0]["label"] = month_dt.strftime("%b %Y")
		columns.insert(1, {"fieldname": "leave_date", "label": _("Date"), "fieldtype": "Data", "width": 150, "align": "center"})

		conditions = "la.employee = %(employee)s AND la.from_date <= %(last_day)s AND la.to_date >= %(first_day)s"
		values = {"employee": selected_emp, "first_day": first_day, "last_day": last_day}
	else:
		conditions = "la.from_date <= %(selected_date)s AND la.to_date >= %(selected_date)s"
		values = {"selected_date": selected_date}

	leaves = frappe.db.sql(
		f"""
		SELECT
			la.employee, la.employee_name, la.leave_type, la.half_day,
			la.from_date, la.to_date, e.attendance_device_id
		FROM `tabLeave Application` la
		JOIN `tabEmployee` e ON e.name = la.employee
		WHERE la.docstatus = 1 AND la.status = 'Approved' AND {conditions}
		ORDER BY la.from_date ASC
		""",
		values,
		as_dict=True,
	)

	data = []
	for leave in leaves:
		row = {
			"employee_name": leave.employee_name,
			"employee_id": leave.attendance_device_id,
			"leave_type": leave.leave_type,
			"full_day": "-" if leave.half_day else "Yes",
		}
		if selected_emp and selected_month:
			row["leave_date"] = selected_date or str(leave.from_date)
		data.append(row)

	return columns, data
