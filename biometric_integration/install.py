import frappe


LEGACY_SETTINGS_FIELDS = (
    "hikcentral_csv_path",
    "hikcentral_duplicate_seconds",
    "enable_hikcentral_csv_sync",
)


def _remove_custom_field(dt, fieldname):
    """Remove an obsolete custom field if it exists."""
    custom_field = frappe.db.get_value(
        "Custom Field",
        {"dt": dt, "fieldname": fieldname},
        "name",
    )
    if custom_field:
        frappe.delete_doc(
            "Custom Field",
            custom_field,
            ignore_permissions=True,
            force=True,
        )


def ensure_custom_fields():
    """Create current integration metadata and remove obsolete fields."""
    for fieldname in LEGACY_SETTINGS_FIELDS:
        _remove_custom_field("Biometric Integration Settings", fieldname)

    # Direct Hikvision integration does not use HikCentral Person IDs.
    # Remove the old Employee field left by the previous HikCentral design.
    _remove_custom_field("Employee", "hikcentral_person_id")

    if not frappe.db.exists(
        "Custom Field",
        {"dt": "Employee Checkin", "fieldname": "hikcentral_event_key"},
    ):
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

    # Device Name is authoritative from the physical Hikvision terminal.
    # Make the child-table field read-only in the database UI definition.
    try:
        from frappe.custom.doctype.property_setter.property_setter import make_property_setter

        make_property_setter(
            "Biometric Device",
            "device_name",
            "read_only",
            1,
            "Check",
        )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Unable to make Biometric Device device_name read-only",
        )

    frappe.db.commit()
