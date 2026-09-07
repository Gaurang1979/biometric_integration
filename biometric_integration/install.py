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
    """Consolidate every movement log into one document per employee/month."""
    if not frappe.db.exists("DocType", MOVEMENT_DOCTYPE):
        return

    logs = frappe.get_all(
        MOVEMENT_DOCTYPE,
        fields=["name", "employee", "employee_name", "month", "log_date"],
        limit_page_length=0,
    )

    groups = {}
    for log in logs:
        if not log.employee:
            continue
        month = log.month or (log.log_date.replace(day=1) if log.log_date else None)
        if not month:
            continue
        groups.setdefault((log.employee, month), []).append(log)

    for (employee, month), source_logs in groups.items():
        target_name = _monthly_log_name(employee, month)
        if frappe.db.exists(MOVEMENT_DOCTYPE, target_name):
            target = frappe.get_doc(MOVEMENT_DOCTYPE, target_name)
        else:
            target = frappe.get_doc({
                "doctype": MOVEMENT_DOCTYPE,
                "name": target_name,
                "employee": employee,
                "employee_name": frappe.db.get_value("Employee", employee, "employee_name") or "",
                "month": month,
                "log_date": month,
            })
            target.insert(ignore_permissions=True)

        for source in source_logs:
            if source.name == target.name:
                continue

            children = frappe.get_all(
                MOVEMENT_ENTRY_DOCTYPE,
                filters={"parent": source.name, "parenttype": MOVEMENT_DOCTYPE},
                fields=["name", "event_time", "device_name"],
                order_by="event_time asc, idx asc",
                limit_page_length=0,
            )
            for child in children:
                values = {
                    "parent": target.name,
                    "parenttype": MOVEMENT_DOCTYPE,
                    "parentfield": "movement_entries",
                }
                if child.event_time:
                    values["event_date"] = child.event_time.date()
                if child.device_name:
                    values["location"] = child.device_name
                frappe.db.set_value(
                    MOVEMENT_ENTRY_DOCTYPE,
                    child.name,
                    values,
                    update_modified=False,
                )

            # Existing integration checkins may point to the old parent.
            if frappe.db.exists("DocType", "Employee Checkin"):
                if frappe.get_meta("Employee Checkin").has_field("biometric_movement_log"):
                    checkins = frappe.get_all(
                        "Employee Checkin",
                        filters={"biometric_movement_log": source.name},
                        pluck="name",
                        limit_page_length=0,
                    )
                    for checkin in checkins:
                        frappe.db.set_value(
                            "Employee Checkin",
                            checkin,
                            "biometric_movement_log",
                            target.name,
                            update_modified=False,
                        )

            frappe.delete_doc(
                MOVEMENT_DOCTYPE,
                source.name,
                ignore_permissions=True,
                force=True,
            )

        # Normalize all rows in the canonical monthly document.
        children = frappe.get_all(
            MOVEMENT_ENTRY_DOCTYPE,
            filters={"parent": target.name, "parenttype": MOVEMENT_DOCTYPE},
            fields=["name", "event_time", "device_name", "event_date", "location"],
            limit_page_length=0,
        )
        for child in children:
            values = {}
            if child.event_time and not child.event_date:
                values["event_date"] = child.event_time.date()
            if child.device_name and not child.location:
                values["location"] = child.device_name
            if values:
                frappe.db.set_value(MOVEMENT_ENTRY_DOCTYPE, child.name, values, update_modified=False)

    frappe.db.commit()

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
