import frappe
from frappe.model.document import Document


class BiometricIntegrationSettings(Document):
    pass


@frappe.whitelist()
def test_device(device_name):
    from biometric_integration.biometric_integration.hikvision import test_device as _test_device
    return _test_device(device_name)


@frappe.whitelist()
def fetch_device_info(device_name):
    from biometric_integration.biometric_integration.hikvision import fetch_device_info as _fetch
    return _fetch(device_name)


@frappe.whitelist()
def sync_attendance(device_name, from_datetime, to_datetime):
    from biometric_integration.biometric_integration.hikvision import sync_device
    return sync_device(device_name, from_datetime, to_datetime)


def scheduled_attendance_sync():
    settings = frappe.get_single("Biometric Integration Settings")
    if not settings.enabled or not settings.scheduler_enabled:
        return
    from biometric_integration.biometric_integration.hikvision import sync_all_devices
    sync_all_devices()
