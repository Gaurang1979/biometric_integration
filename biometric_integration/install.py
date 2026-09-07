import frappe
from hashlib import sha1


LEGACY_SETTINGS_FIELDS = (
    "hikcentral_csv_path",
    "hikcentral_duplicate_seconds",
    "enable_hikcentral_csv_sync",
)

MOVEMENT_DOCTYPE = "Daily Employee Movement Log"
MOVEMENT_ENTRY_DOCTYPE = "Daily Employee Movement Entry"


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


def _monthly_log_name(employee, month):
    digest = sha1(f"{employee}|{month}".encode()).hexdigest()[:16]
    return f"MOV-{digest}"


def migrate_movement_logs_to_monthly():
    """Consolidate legacy daily logs into one document per employee/month.

    Existing child rows are moved, not recreated, so event keys and existing
    Employee Checkin links remain intact. The operation is idempotent.
    """
    if not frappe.db.exists("DocType", MOVEMENT_DOCTYPE):
        return

    legacy_logs = frappe.get_all(
        MOVEMENT_DOCTYPE,
        filters={"month": ["is", "not set"]},
        fields=["name", "employee", "employee_name", "log_date"],
        limit_page_length=0,
    )

    for legacy in legacy_logs:
        if not legacy.employee or not legacy.log_date:
            continue

        month = legacy.log_date.replace(day=1)
        target_name = _monthly_log_name(legacy.employee, month)

        if frappe.db.exists(MOVEMENT_DOCTYPE, target_name):
            target = frappe.get_doc(MOVEMENT_DOCTYPE, target_name)
        else:
            target = frappe.get_doc({
                "doctype": MOVEMENT_DOCTYPE,
                "name": target_name,
                "employee": legacy.employee,
                "employee_name": legacy.employee_name or frappe.db.get_value("Employee", legacy.employee, "employee_name") or "",
                "month": month,
            })
            target.insert(ignore_permissions=True)

        children = frappe.get_all(
            MOVEMENT_ENTRY_DOCTYPE,
            filters={"parent": legacy.name, "parenttype": MOVEMENT_DOCTYPE},
            fields=["name", "event_time", "event_date"],
            order_by="event_time asc, idx asc",
            limit_page_length=0,
        )

        for child in children:
            if not child.event_date and child.event_time:
                frappe.db.set_value(
                    MOVEMENT_ENTRY_DOCTYPE,
                    child.name,
                    "event_date",
                    child.event_time.date(),
                    update_modified=False,
                )
            frappe.db.set_value(
                MOVEMENT_ENTRY_DOCTYPE,
                child.name,
                {
                    "parent": target.name,
                    "parenttype": MOVEMENT_DOCTYPE,
                    "parentfield": "movement_entries",
                },
                update_modified=False,
            )

        if frappe.db.exists(MOVEMENT_DOCTYPE, legacy.name):
            frappe.delete_doc(
                MOVEMENT_DOCTYPE,
                legacy.name,
                ignore_permissions=True,
                force=True,
            )

    frappe.db.commit()

    # Reconcile all consolidated logs so movement direction and existing/new
    # Employee Checkins reflect the new per-day/per-device session rules.
    try:
        from biometric_integration.biometric_integration.attendance_sync import _reconcile_monthly_log

        monthly_logs = frappe.get_all(
            MOVEMENT_DOCTYPE,
            filters={"month": ["is", "set"]},
            pluck="name",
            limit_page_length=0,
        )
        for name in monthly_logs:
            try:
                _reconcile_monthly_log(frappe.get_doc(MOVEMENT_DOCTYPE, name))
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Movement log reconciliation failed during migration: {name}",
                )
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Monthly movement log reconciliation import failed",
        )


def ensure_custom_fields():
    """Create current integration metadata and remove obsolete fields."""
    for fieldname in LEGACY_SETTINGS_FIELDS:
        _remove_custom_field("Biometric Integration Settings", fieldname)

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

    _ensure_custom_field("biometric_event_key", "Biometric Event Key")
    _ensure_custom_field("biometric_session_key", "Biometric Session Key")
    _ensure_custom_field(
        "biometric_movement_log",
        "Daily Movement Log",
        fieldtype="Link",
        options=MOVEMENT_DOCTYPE,
    )

    try:
        from frappe.custom.doctype.property_setter.property_setter import make_property_setter
        make_property_setter("Biometric Device", "device_name", "read_only", 1, "Check")
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Unable to make Biometric Device device_name read-only",
        )

    migrate_movement_logs_to_monthly()
