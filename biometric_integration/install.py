import frappe


LEGACY_SETTINGS_FIELDS = (
    "hikcentral_csv_path",
    "hikcentral_duplicate_seconds",
    "enable_hikcentral_csv_sync",
)


def _remove_custom_field(dt, fieldname):
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


def _ensure_custom_field(fieldname, label, fieldtype="Data", options=None):
    if frappe.db.exists(
        "Custom Field",
        {"dt": "Employee Checkin", "fieldname": fieldname},
    ):
        return

    field = {
        "doctype": "Custom Field",
        "dt": "Employee Checkin",
        "fieldname": fieldname,
        "label": label,
        "fieldtype": fieldtype,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "device_id",
    }
    if options:
        field["options"] = options
    frappe.get_doc(field).insert(ignore_permissions=True)


def ensure_custom_fields():
    """Create current integration metadata and remove obsolete fields."""
    for fieldname in LEGACY_SETTINGS_FIELDS:
        _remove_custom_field("Biometric Integration Settings", fieldname)

    _remove_custom_field("Employee", "hikcentral_person_id")

    # Kept for compatibility with existing installations. New attendance
    # processing uses the direct-device fields below and never requires
    # HikCentral.
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

    _ensure_custom_field("biometric_event_key", "Biometric Event Key")
    _ensure_custom_field("biometric_session_key", "Biometric Session Key")
    _ensure_custom_field(
        "biometric_movement_log",
        "Daily Movement Log",
        fieldtype="Link",
        options="Daily Employee Movement Log",
    )

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
