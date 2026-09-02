import frappe
from frappe.model.document import Document


class BiometricIntegrationSettings(Document):
    pass


@frappe.whitelist()
def test_device(device_name):
    """Test one specific Hikvision device."""
    from biometric_integration.biometric_integration.hikvision import test_device as _test_device
    return _test_device(device_name)


@frappe.whitelist()
def fetch_device_info(device_name):
    """Fetch information from one specific Hikvision device."""
    from biometric_integration.biometric_integration.hikvision import fetch_device_info as _fetch
    return _fetch(device_name)


@frappe.whitelist()
def fetch_all_device_info():
    """Fetch and save Hikvision information for every enabled device."""
    settings = frappe.get_single("Biometric Integration Settings")
    results = []

    from biometric_integration.biometric_integration.hikvision import fetch_device_info as _fetch

    for row in settings.devices or []:
        if not row.enabled:
            continue

        try:
            result = _fetch(row.name)
            item = {
                "name": row.name,
                "device_name": row.device_name or row.ip,
                "ip": row.ip,
                "status": result.get("status"),
            }

            if result.get("status") == "success":
                info = result.get("device") or {}
                item.update({
                    "device_name": info.get("device_name") or row.device_name or row.ip,
                    "device_id": info.get("device_id", ""),
                    "model": info.get("model", ""),
                    "serial_number": info.get("serial_number", ""),
                    "mac_address": info.get("mac_address", ""),
                })
            else:
                item["message"] = result.get("message") or "Unable to fetch device information"
                if result.get("http_status"):
                    item["http_status"] = result["http_status"]

        except Exception as exc:
            frappe.log_error(
                frappe.get_traceback(),
                f"Hikvision device information failed: {row.device_name or row.ip}",
            )
            item = {
                "name": row.name,
                "device_name": row.device_name or row.ip,
                "ip": row.ip,
                "status": "error",
                "message": str(exc),
            }

        results.append(item)

    return {"devices": results}


@frappe.whitelist()
def sync_attendance(from_datetime, to_datetime):
    """Import attendance from every enabled Hikvision device."""
    from biometric_integration.biometric_integration.hikvision import sync_all_devices
    return sync_all_devices(
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        require_scheduler=False,
    )


def scheduled_attendance_sync():
    """Run the configured scheduled synchronization for all enabled devices."""
    settings = frappe.get_single("Biometric Integration Settings")
    if not settings.enabled or not settings.scheduler_enabled:
        return

    from biometric_integration.biometric_integration.hikvision import sync_all_devices
    return sync_all_devices(require_scheduler=True)
