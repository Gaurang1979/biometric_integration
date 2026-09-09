app_name = "biometric_integration"
app_title = "Biometric Integration"
app_publisher = "Sundaram Technologies"
app_description = "Direct Hikvision biometric device integration for ERPNext HRMS"
app_email = ""
app_license = "MIT"
app_icon = "octicon octicon-fingerprint"
app_logo_url = "/assets/biometric_integration/images/biometric_integration_logo.svg"

# ERPNext/HRMS are required for the biometric integration to function.
required_apps = ["erpnext", "hrms"]

scheduler_events = {
    "cron": {
        "*/10 * * * *": [
            "biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings.scheduled_attendance_sync"
        ]
    }
}

# Run after both `bench install-app` and every `bench migrate`/`bench update`.
after_install = [
    "biometric_integration.install.ensure_custom_fields"
]

after_migrate = [
    "biometric_integration.install.ensure_custom_fields"
]
