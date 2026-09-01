import frappe


LEGACY_SETTINGS_FIELDS = (
    "hikcentral_csv_path",
    "hikcentral_duplicate_seconds",
    "enable_hikcentral_csv_sync",
)


def ensure_custom_fields():
    """Create current integration metadata and remove obsolete CSV settings."""
    for fieldname in LEGACY_SETTINGS_FIELDS:
        custom_field = frappe.db.get_value(
            "Custom Field",
            {"dt": "Biometric Integration Settings", "fieldname": fieldname},
            "name",
        )
        if custom_field:
            frappe.delete_doc("Custom Field", custom_field, ignore_permissions=True, force=True)

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
