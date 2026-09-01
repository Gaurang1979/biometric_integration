# Hikvision Biometric Integration — HR User Guide

## 1. Purpose

This guide explains how HR and authorized administrators configure and use the Hikvision biometric integration with ERPNext HRMS.

The integration reads attendance events directly from supported Hikvision access-control terminals and creates standard ERPNext **Employee Checkin** records.

> **Privacy and security:** Never place employee personal data, production URLs, IP addresses, passwords, API keys, certificates, or other site-specific information in this documentation. Use placeholders when documenting a deployment.

## 2. How the integration works

```text
Hikvision Terminal(s)
        |
        | Direct ISAPI / HTTP(S)
        v
Biometric Integration Settings
        |
        | Employee Device ID matching
        v
ERPNext Employee
        |
        v
Employee Checkin
        |
        v
ERPNext HRMS Attendance
```

Illustrative diagrams are provided in `docs/images/`.

## 3. Who should use this guide

### HR users

HR normally needs to:

- maintain the employee's Attendance Device ID;
- check Employee Checkin records;
- verify attendance when a punch is missing or unexpected;
- report device or synchronization problems to the ERPNext administrator.

### ERPNext administrator

The administrator is responsible for:

- installing/updating the application;
- configuring Hikvision devices;
- entering device network and authentication settings;
- testing devices;
- performing the first manual import;
- enabling automatic synchronization;
- troubleshooting connection and mapping problems.

HR users should not change device passwords, network settings, scheduler settings, or application code unless they are also authorized administrators.

## 4. Prerequisites

Before configuration, confirm:

1. ERPNext and HRMS are installed and working.
2. The biometric integration application is installed on the ERPNext site.
3. The Hikvision terminal is reachable from the ERPNext server.
4. The Hikvision device supports the ISAPI access-control event interface used by this application.
5. The device administrator username/password is available to the authorized administrator.
6. Each employee has a unique attendance identifier on the biometric device.
7. That same identifier is entered in ERPNext Employee → **Attendance Device ID**.
8. The device location latitude and longitude are known if HRMS geolocation validation is enabled.

## 5. Employee master setup

Employee mapping is based on the biometric device ID, **not the employee name**.

### Step-by-step

1. Open **Employee**.
2. Open the employee who will use the biometric terminal.
3. Locate **Attendance Device ID (Biometric/RF tag ID)**.
4. Enter exactly the same identifier used by the Hikvision terminal.
5. Save the Employee record.

Example using placeholders:

| Hikvision value | ERPNext field |
|---|---|
| `EMP001` | Employee → Attendance Device ID = `EMP001` |
| `EMP002` | Employee → Attendance Device ID = `EMP002` |

Do not use an employee name as the device ID unless the Hikvision system itself uses that name as its employee number.

## 6. Open Biometric Integration Settings

Use the ERPNext search/awesome bar to open:

**Biometric Integration Settings**

The settings record contains one parent configuration and a child table containing one row for each Hikvision terminal.

### Recommended initial settings

| Setting | Initial value | Purpose |
|---|---:|---|
| Enable Biometric Integration | Enabled | Turns on the integration |
| Duplicate Grouping Window | 30 seconds | Groups repeated events from the same attendance action |
| Enable Automatic Synchronization | Disabled | Keep off during first setup/testing |
| Automatic Sync Window | 30 minutes | Initial look-back window when automatic sync is later enabled |

The exact field labels may vary slightly with the installed ERPNext version.

## 7. Add a Hikvision device

In **Hikvision Devices**, add one child row for each terminal.

### Device fields

| Field | What to enter |
|---|---|
| Enabled | Enable after the device details are ready |
| Device Name | A meaningful local name, e.g. `Main Entrance` |
| Protocol | `HTTP` or `HTTPS`, according to the terminal configuration |
| IP Address / Host | Hikvision device hostname or IP address |
| Port | Device HTTP/HTTPS port, commonly 80 or 443 |
| Username | Authorized Hikvision account |
| Password | Authorized Hikvision account password |
| Device ID | Leave blank initially; populate from device information when supported |
| Model | Leave blank initially; populate from device information when supported |
| Serial Number | Leave blank initially; populate from device information when supported |
| MAC Address | Leave blank initially; populate from device information when supported |
| Latitude | Device/site latitude |
| Longitude | Device/site longitude |
| Timezone | Device timezone, e.g. `Asia/Kolkata` for India |

### Security recommendation

Use HTTPS where the terminal and network configuration support it. Never document or commit the device password to source control.

## 8. Test the device before synchronization

After saving the device configuration:

1. Use **Test Connection** / the available device test action.
2. Confirm that the device responds successfully.
3. Use **Fetch Device Info** if available.
4. Confirm the model and device identity.
5. Correct any network, authentication, protocol, or port errors before continuing.

The integration communicates directly with the terminal using Hikvision ISAPI and HTTP Digest authentication where required.

## 9. First attendance import — recommended procedure

**Do not enable automatic synchronization for the first test.**

Use the manual import function to test a small historical period.

Recommended procedure:

1. Choose a short period for which you know the expected punches.
2. Run **Import Attendance**.
3. Review the import result.
4. Open **Employee Checkin**.
5. Filter by the relevant employee and date/time.
6. Confirm that the expected check-ins were created.
7. Confirm that the employee is the correct ERPNext Employee.
8. Confirm that the time is correct.
9. Confirm the device ID and event key are present.
10. Confirm latitude and longitude are populated when required by HRMS.

Only after the manual test is correct should automatic synchronization be enabled.

## 10. Understanding Employee Checkin

The integration creates standard ERPNext **Employee Checkin** records rather than a separate attendance database.

Important fields include:

| Employee Checkin field | Meaning |
|---|---|
| Employee | ERPNext Employee matched by Attendance Device ID |
| Employee Name | Employee name from ERPNext |
| Log Type | IN or OUT |
| Time | Attendance event time |
| Location / Device ID | Configured Hikvision device identity |
| HikCentral Event Key | Unique event key used for duplicate prevention |
| Latitude | Configured device latitude |
| Longitude | Configured device longitude |

## 11. How employee mapping works

The key rule is:

```text
Hikvision employeeNoString
          |
          v
Employee.attendance_device_id
          |
          v
ERPNext Employee
          |
          v
Employee Checkin
```

If the device reports `EMP001`, ERPNext searches for an Employee whose **Attendance Device ID** is exactly `EMP001`.

If no matching Employee exists, the event should not be treated as a valid employee attendance record. The administrator should correct the employee master data and then re-import the appropriate period.

## 12. IN / OUT behavior

Some Hikvision event responses do not provide a reliable explicit IN/OUT direction. In that situation, the integration determines the next log type from the employee's previous ERPNext Employee Checkin and alternates IN/OUT.

Therefore:

- the first imported punch for an employee may be interpreted as **IN**;
- the next valid punch is interpreted as **OUT**;
- subsequent punches alternate in the same manner.

HR should investigate unusual sequences instead of manually changing many records without understanding the source events.

## 13. Duplicate event handling

Biometric terminals can produce several closely timed authentication events for one physical attendance action, for example when multiple authentication modalities are involved.

The integration uses:

1. a device/event key for duplicate prevention; and
2. a configurable duplicate grouping window.

The default grouping window is **30 seconds**.

If legitimate separate punches occur within that window, an administrator may need to review the configuration and business process rather than blindly increasing the value.

## 14. Automatic synchronization

After the manual test is successful:

1. Open **Biometric Integration Settings**.
2. Confirm **Enable Biometric Integration** is enabled.
3. Confirm every production device that should synchronize is enabled.
4. Confirm device timezone and coordinates are correct.
5. Set **Enable Automatic Synchronization** to enabled.
6. Save.
7. Monitor Employee Checkin for new events.

The application scheduler periodically checks enabled devices. The application is designed so that automatic synchronization is disabled until an administrator explicitly enables it.

## 15. Adding multiple devices

Repeat the same device configuration for each terminal.

Example:

| Device Name | Location | Enabled |
|---|---|---|
| Main Entrance | Head Office | Yes |
| Production Entrance | Factory | Yes |
| Branch Entrance | Branch Office | Yes |

Each device should have its own network address, credentials, timezone and coordinates.

Employee identifiers should remain unique and consistently maintained across the biometric environment.

## 16. Daily HR operation

HR generally does not need to interact with the biometric device configuration every day.

### Daily checks

- Review Employee Checkin when attendance is disputed.
- Confirm new employees have an Attendance Device ID before they start using biometric attendance.
- Confirm transferred employees retain the correct biometric identifier.
- Report missing punches to the administrator with the employee, date and approximate time.

### Do not

- create duplicate employees to solve a biometric mapping issue;
- change Attendance Device ID without checking the value on the terminal;
- delete Employee Checkin records as a first troubleshooting step;
- change device passwords in ERPNext without also updating the terminal configuration;
- enable automatic synchronization before completing a manual test.

## 17. New employee procedure

When a new employee is added:

1. Create the Employee record in ERPNext.
2. Create/register the employee on the Hikvision terminal using the organization's normal biometric enrollment procedure.
3. Note the exact biometric employee number/identifier.
4. Enter that value in ERPNext **Attendance Device ID**.
5. Save the Employee.
6. Perform one controlled attendance test.
7. Confirm the resulting Employee Checkin belongs to the correct employee.

## 18. Employee transfer or replacement device

When an employee moves between locations or devices:

1. Confirm whether the biometric employee identifier is retained or changed.
2. Update the Hikvision device(s) according to the organization's master-data procedure.
3. Update ERPNext Attendance Device ID only if the identifier actually changed.
4. Test the employee on the new terminal.
5. Check the Employee Checkin record.

Do not create a second ERPNext employee merely because the employee uses another terminal.

## 19. Troubleshooting guide

### Problem: Device connection fails

Check:

- device power/network status;
- server-to-device network reachability;
- IP/hostname;
- protocol HTTP vs HTTPS;
- port;
- username/password;
- firewall rules;
- Hikvision account permissions.

### Problem: Device connects but no employee is created

Check:

- Hikvision `employeeNoString`;
- ERPNext Employee → Attendance Device ID;
- exact spelling/capitalization;
- whether the employee is active and correctly configured.

Do not rely on the employee name for mapping.

### Problem: Checkin creation fails because of location

Confirm that the device row contains valid latitude and longitude. HRMS installations with geolocation tracking may require these values.

### Problem: Duplicate punches appear

Check:

- Hikvision event timing;
- duplicate grouping window;
- whether the same event key is being reused;
- whether multiple devices are legitimately generating separate events.

### Problem: Time is incorrect

Check:

- Hikvision device clock;
- device timezone;
- ERPNext/site timezone;
- daylight-saving behavior where applicable.

For India, use `Asia/Kolkata` rather than a manually entered fixed offset.

### Problem: Automatic sync does not run

Check:

1. Enable Biometric Integration.
2. Enable Automatic Synchronization.
3. Device row Enabled status.
4. ERPNext scheduler/workers.
5. Device connectivity.
6. Last Sync / Last Sync Status.

An administrator should inspect ERPNext worker and scheduler status if the configuration is correct but no new records appear.

## 20. Recommended support information

When reporting an issue, HR should provide:

- employee name;
- employee Attendance Device ID;
- date;
- approximate attendance time;
- device/location name;
- expected result;
- actual result;
- screenshot of the relevant ERPNext record, with passwords and sensitive information hidden.

Never send passwords or API secrets in a support ticket.

## 21. Administrator checklist

### Initial installation

- [ ] Install the application.
- [ ] Run ERPNext migration.
- [ ] Clear cache/restart services.
- [ ] Open Biometric Integration Settings.
- [ ] Configure duplicate grouping.
- [ ] Add devices.
- [ ] Test each device.
- [ ] Configure employee Attendance Device IDs.
- [ ] Perform manual attendance import.
- [ ] Verify Employee Checkin.
- [ ] Enable automatic synchronization.

### Production readiness

- [ ] All devices have meaningful names.
- [ ] All device credentials are stored only in ERPNext/secure password management.
- [ ] No production credentials exist in Git.
- [ ] Device timezones are correct.
- [ ] Device coordinates are correct.
- [ ] Employee identifiers are unique.
- [ ] Manual test has passed.
- [ ] Scheduler is running.
- [ ] HR knows the troubleshooting procedure.

## 22. Privacy and source-control rules

This application may process attendance information. Production employee data and device credentials must remain in the ERPNext instance and secure infrastructure.

Do **not** commit any of the following to GitHub:

- employee names or employee lists;
- biometric templates;
- attendance exports containing personal data;
- production IP addresses/hostnames;
- ERPNext site URLs;
- usernames/passwords;
- API keys or secrets;
- private certificates;
- database backups.

Documentation in this repository intentionally uses generic placeholders so that the module can be shared publicly.

## 23. Technical notes for administrators

The current direct-device implementation uses the Hikvision ISAPI access-control event endpoint and HTTP Digest authentication. Successful attendance events are imported from the supported event type configured in the application. The application intentionally ignores unsupported/irrelevant event types.

The exact event capabilities vary by Hikvision model and firmware. Always test a new model/firmware combination before enabling automatic production synchronization.

## 24. Version compatibility

The module is designed around ERPNext/Frappe HRMS standard Employee and Employee Checkin records. ERPNext/HRMS APIs and DocType fields can change between major versions.

For a new ERPNext major version:

1. install in a test environment;
2. run migrations;
3. verify the Employee Attendance Device ID field;
4. verify Employee Checkin fields;
5. test device connection;
6. perform a manual import;
7. only then deploy to production.

## 25. Quick reference

**Employee mapping:** Employee → Attendance Device ID

**Device configuration:** Biometric Integration Settings → Hikvision Devices

**First test:** Manual Import → Employee Checkin verification

**Production automation:** Enable Automatic Synchronization

**Attendance record:** Employee Checkin

**Primary duplicate protection:** Hikvision event key + grouping window

**Do not store in Git:** passwords, URLs, IPs, employee data, secrets
