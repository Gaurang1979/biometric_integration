# Biometric Integration

Direct Hikvision ISAPI integration for ERPNext HRMS.

## Current scope

- Multiple Hikvision devices in one `Biometric Integration Settings` record.
- Direct `POST /ISAPI/AccessControl/AcsEvent?format=json` communication using HTTP Digest authentication.
- Imports successful access events only (`major=5`, `minor=75`).
- Maps Hikvision `employeeNoString` to ERPNext `Employee.attendance_device_id`.
- Creates standard ERPNext `Employee Checkin` records.
- Uses each device's fixed latitude/longitude for HRMS geolocation validation.
- Preserves the timestamp offset supplied by the device and converts it to the configured device timezone.
- Uses device identity + Hikvision `serialNo` as the event key for duplicate prevention.
- Groups repeated successful authentication events within the configured window.
- Provides manual import and device test methods.
- Automatic synchronization is disabled by default and must be enabled in settings.

## Important behavior

The tested DS-K1T320MFWX returns `minor=21` and `minor=22` events around successful `minor=75` events. These are intentionally ignored for attendance. The successful `minor=75` event does not expose an explicit IN/OUT field in the tested response, so the integration alternates IN/OUT based on the previous ERPNext Employee Checkin for that employee.

## Configuration

1. Install the app on the ERPNext site.
2. Run migrate.
3. Open **Biometric Integration Settings**.
4. Add one row per Hikvision terminal.
5. Enter IP, username, password, latitude, longitude and timezone (`Asia/Kolkata` for India).
6. Use **Fetch Device Info** / **Test All Devices**.
7. Use **Import Attendance** for a controlled historical test.
8. Inspect the generated **Employee Checkin** records.
9. Only then enable **Automatic Synchronization**.

## Employee mapping

Set each employee's **Attendance Device ID** to exactly match the Hikvision `employeeNoString`, for example `BO10`.

## Safety

The scheduler is disabled by default. It will not import anything until `Enable Biometric Integration` and `Enable Automatic Synchronization` are enabled.
