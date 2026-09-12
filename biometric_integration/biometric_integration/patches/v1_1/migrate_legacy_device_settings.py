# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Runs BEFORE the doctype schema is migrated, while the old ip/username/
	password columns still exist on Biometric Integration Settings, so we can
	carry the single legacy device forward into the new Biometric Device
	doctype instead of silently losing the credentials.
	"""
	if not frappe.db.table_has_column("Biometric Integration Settings", "ip"):
		return

	old = frappe.db.get_value(
		"Biometric Integration Settings",
		"Biometric Integration Settings",
		["ip", "username", "password", "device_name", "device_id", "model", "device_serial_number", "mac_address"],
		as_dict=True,
	)

	if not old or not old.get("ip"):
		return

	device_name = old.get("device_name") or old.get("ip")

	if frappe.db.exists("Biometric Device", device_name):
		return

	if not frappe.db.exists("DocType", "Biometric Device"):
		# New doctype not migrated yet in this run - skip, nothing we can do safely.
		return

	device = frappe.new_doc("Biometric Device")
	device.device_name = device_name
	device.ip = old.get("ip")
	device.username = old.get("username")
	# `password` column stores the encrypted value directly; set_password re-encrypts,
	# so write the already-encrypted value straight to the db field instead.
	device.protocol = "http"
	device.port = 80
	device.device_id = old.get("device_id")
	device.model = old.get("model")
	device.device_serial_number = old.get("device_serial_number")
	device.mac_address = old.get("mac_address")
	device.insert(ignore_permissions=True)

	if old.get("password"):
		frappe.db.set_value("Biometric Device", device.name, "password", old.get("password"))

	frappe.db.commit()
	frappe.logger().info(
		f"biometric_integration: migrated legacy single-device settings into Biometric Device '{device.name}'."
	)
