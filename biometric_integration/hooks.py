app_name = "biometric_integration"
app_title = "Biometric Integration"
app_publisher = "Sundaram Technologies"
app_description = "Direct Hikvision biometric device integration for ERPNext HRMS"
app_email = ""
app_license = "MIT"

scheduler_events = {
    "cron": {
        "*/10 * * * *": [
            "biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings.scheduled_attendance_sync"
        ]
    }
}

after_migrate = [
    "biometric_integration.install.ensure_custom_fields"
]
