import frappe


def ensure_custom_fields():
    """Create integration metadata without touching existing user customizations."""
    if not frappe.db.exists("Custom Field", {"dt": "Employee Checkin", "fieldname": "hikcentral_event_key"}):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Employee Checkin",
            "fieldname": "hikcentral_event_key",
            "label": "Biometric Event Key",
            "fieldtype": "Data",
            "unique": 1,
            "read_only": 1,
            "hidden": 1,
            "insert_after": "device_id",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
