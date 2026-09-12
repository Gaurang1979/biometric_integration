# Biometric Integration — Multi-Device Direct Sync (v1.1)

This is a drop-in rewrite of the device/attendance-sync parts of the app.
It does **not** touch `Biometric Attendance Log` / `Biometric Attendance
Punch Table` history data — nothing is deleted automatically.

## What changed

| # | Ask | What was built |
|---|-----|-----------------|
| 1 | Back to direct-device sync, multiple devices | New **Biometric Device** doctype (one row per Hikvision unit: IP, port, protocol, credentials, its own timezone offset). `device_sync.py` polls every enabled device over ISAPI. |
| 2 | Stop writing to a duplicate doctype | Sync now writes straight into the standard **Employee Checkin** doctype (what Shift Type auto-attendance / Payroll actually read). `Biometric Manual Punch` does the same. |
| 3 | Clear old settings | `Biometric Integration Settings` stripped down to only the log-retention fields. All device fields moved to `Biometric Device`. See "Migration" below — nothing is force-deleted. |
| 4 | Mobile app APIs | `mobile_api.py`: `mobile_checkin_push`, `mobile_checkin_bulk_push`, `mobile_employee_list`. Auth = standard Frappe API Key/Secret. |
| 5 | Field mapping + employee sync-back | New **Biometric Field Mapping Settings** (with child table `Biometric Field Mapping Row`) maps ERPNext Employee fields ↔ Hikvision `UserInfo` fields ↔ mobile payload fields, per direction. `employee_sync.py` pushes Employee changes to all enabled devices and/or a mobile webhook on save. |
| 6 | Fix gaps vs. original repo | Found and documented: dead HikCentral settings fields (referenced in code, never in the doctype JSON — this is why server sync looked broken), hardcoded `+08:00` timezone, Wednesday-skipping cron, no role checks on face/name endpoints (now `frappe.only_for`), no dedup key on direct-device sync (added SHA-256 `biometric_event_id`, same pattern `hikcentral_csv.py` already used correctly). |

## New / changed files
```
biometric_integration/
  device_sync.py                                   (new)
  mobile_api.py                                     (new)
  employee_sync.py                                  (new)
  hikcentral_csv.py                                 (unchanged logic, marked deprecated, unscheduled)
  hooks.py                                           (doc_events + scheduler_events updated)
  patches.txt                                        (new entries)
  patches/v1_1/migrate_legacy_device_settings.py     (new — pre_model_sync)
  patches/v1_1/add_employee_checkin_custom_fields.py (new — post_model_sync)
  biometric_integration/doctype/
    biometric_device/                                (new doctype)
    biometric_field_mapping_settings/                (new doctype)
    biometric_field_mapping_row/                      (new child doctype)
    biometric_integration_settings/                  (stripped down)
    biometric_manual_punch/                          (now writes Employee Checkin)
```

## Migration steps (staging first)

1. `bench --site <site> migrate`
   - `pre_model_sync` patch copies your existing single device's IP/username/password
     into a new `Biometric Device` record automatically, before the old columns are dropped.
   - `post_model_sync` patches add: two hidden custom fields on `Employee Checkin`
     (`biometric_event_id`, `biometric_manual_punch`); the `biometric_access` table on
     Employee (device/location access rules); and two more hidden `Employee Checkin`
     fields for anti-passback flagging (`flagged_anti_passback`, `flag_reason`).
2. Open **Biometric Device** → confirm the migrated device looks right (protocol defaults
   to `http`, port `80` — adjust if yours differs) → click **Test Connection**.
3. Add any additional devices the same way.
4. Set each device's **Device Timezone Offset** (e.g. `+05:30`) — this was hardcoded to
   `+08:00` before regardless of your actual location.
5. Open **Biometric Field Mapping Settings** and add rows, e.g.:

   | Target System | ERPNext Field | External Field | Direction |
   |---|---|---|---|
   | Hikvision Device | employee_name | name | ERPNext to External |
   | Hikvision Device | attendance_device_id | employeeNo | ERPNext to External |
   | Mobile App | employee_name | full_name | ERPNext to External |
   | Mobile App | attendance_device_id | emp_code | ERPNext to External |

6. Toggle **Push Employee Changes to Hikvision Devices** / **...to Mobile App** as needed,
   and set the mobile webhook URL if used.
7. Your existing `Biometric Attendance Log` history is untouched — it's just no longer
   written to going forward. Once you've confirmed Employee Checkin is populating
   correctly, you can archive/export that data and delete the doctype yourself when ready
   (deliberately left as a manual step).
8. Scheduler now runs `device_sync.sync_all_devices` every 15 minutes
   (`hooks.py` → `scheduler_events["cron"]`) — change the cron string if you need a
   different interval.

## Mobile app integration

Auth: create a Frappe user for the mobile app (or per field agent), generate an
**API Key/Secret** under that User, and send `Authorization: token <key>:<secret>`.

```bash
# push one checkin
curl -X POST https://<site>/api/method/biometric_integration.biometric_integration.mobile_api.mobile_checkin_push \
  -H "Authorization: token <key>:<secret>" -H "Content-Type: application/json" \
  -d '{"employee":"HR-EMP-0001","time":"2026-09-11 09:03:00","log_type":"IN","device_id":"mobile-01"}'

# push a batch
curl -X POST .../mobile_checkin_bulk_push \
  -d '{"events":[{"employee":"HR-EMP-0001","time":"2026-09-11 09:03:00"}, ...]}'

# pull employee master (delta sync)
curl "https://<site>/api/method/biometric_integration.biometric_integration.mobile_api.mobile_employee_list?modified_after=2026-09-01 00:00:00"
```

`mobile_employee_list` returns fields shaped per your **Mobile App** rows in the field
mapping settings (falls back to `name`, `employee_name`, `attendance_device_id` if no
mapping rows exist yet).

## Capture-at-device, then replicate everywhere (new)

Matches how HikCentral is used today: employee enrolls face + fingerprint
physically at ONE device (its own touchscreen/sensor), then ERPNext pulls
that data back and pushes it to every other device. New doctype
**Employee Biometric Template** becomes the ERPNext-side source of truth
(the role HikCentral used to play) so adding a device later is just
"push saved template" — no need to revisit the original device.

Employee form buttons:
- **Pull From Device & Replicate to All** — pick the device the employee
  just enrolled at, choose face and/or fingerprint, and it pulls + pushes
  to every other enabled device in one go.
- **Push Saved Template to All Devices** — re-push what's already saved
  (e.g. after adding a new device).

**Face**: pulled as a plain image (`UserInfo/Search` → faceURL/faceData),
fully portable across devices — this path is solid.

**Fingerprint**: pulled/pushed via `FingerPrintUpload` / `FingerPrintDownload`
ISAPI calls. This is genuinely best-effort — Hikvision fingerprint
templates are a proprietary binary format and **portability across
device models/firmware isn't guaranteed by Hikvision itself**, let alone
by this integration. If a push fails on a given device, the fallback is
re-enrolling that one finger locally at that terminal — the UI reports
per-device success/failure so you know exactly where that's needed.

## Employee master biometric buttons (photo-upload path)

Employee form now shows a **Biometric** button group (added via `hooks.py`
`doctype_js` → `public/js/employee.js`, no core Employee doctype changes):

- **Enroll Face on Devices** — pushes the Employee's standard `image` field
  to every enabled device as a face template (`biometric_enrollment.py`).
  Uses the documented ISAPI `UserFace/Record` multipart upload. The photo
  capture itself needs no new UI - Employee's `image` field's built-in
  upload dialog already has a webcam "Capture" tab.
- **Enroll Fingerprint (Experimental)** — best-effort device-initiated
  capture trigger. **Not guaranteed to work on every model/firmware** -
  most Hikvision terminals expect fingerprint capture to happen at the
  terminal itself or via a local USB enrollment reader. Check
  `GET /ISAPI/System/capabilities` on your device before relying on this.
- **Sync to Devices Now** — runs the field-mapping push (name/employeeNo/etc.)
  immediately instead of waiting for the next save.
- **Check Enrollment Status** — queries each device for whether this
  employee's user record and face exist.

All of this requires **Attendance Device ID** to be set on the Employee
(the field ERPNext already uses as the device employeeNo) and an uploaded
photo for face enrollment.

## Audit log + device health monitoring (new)

Two more gaps closed, since this is now a physical access-control system,
not just an attendance importer:

- **Biometric Audit Log** — every enroll, revoke, and manual punch is
  recorded (who did it, when, on which device, success/fail). HR Manager
  gets read-only access; System Manager can manage it. This is the kind
  of audit trail a compliance/security review will ask for and HikCentral
  would otherwise have been providing.
- **Device health monitoring** (`device_health.py`, runs every 10 min) —
  pings every enabled device and tracks `Online` / `Last Seen Online` on
  the Biometric Device record. Sends **one** email alert on an
  online→offline *transition* (not a repeat every 10 minutes) to the
  addresses in **Biometric Integration Settings → Device Offline Alert
  Recipients**. A door device silently going offline is a real access
  and attendance gap - this catches it instead of you finding out when
  someone can't get in.

## Field-mapping fix for access-controlled enrollment

The gap flagged earlier is closed: when **Enable Device-Wise Access
Control** is on, the enroll step now applies your full Hikvision field
mapping rows (name, department, etc.) via the same path as the
unrestricted push, instead of only setting `employeeNo` + `name`.

## Other features worth considering (not built yet - say the word)

- **Anti-passback / re-entry cooldown** — block a checkin at Device B
  within N minutes of a checkin at Device A for the same person (catches
  buddy-punching / tailgating patterns).
- **Visitor / temporary badge doctype** — same device-push mechanism as
  Employee, but for non-employees (contractors, visitors) with a hard
  expiry, auto-revoked via the scheduler once expired.
- **Late/absent real-time alert** — notify a manager if an employee's
  expected shift start passes with no Employee Checkin.
- **Bulk provisioning tool** — select 50 employees + a device, one click
  to enroll/revoke all of them (currently one employee at a time).
- **Device time-sync check** — flag devices whose clock has drifted from
  the ERPNext server (breaks event ordering / dedup if it drifts far).
- **Self-service "My Access" employee portal report** — lets an employee
  see which doors they're currently authorized for, without HR access.

## Six more features (all built - this batch)

1. **Anti-passback detection** (`anti_passback.py`) - flags an Employee
   Checkin if the same employee checked in at a *different* device within
   **Anti-Passback Cooldown (minutes)** (Settings). Honest limitation
   stated plainly: this cannot block the door in real time - devices are
   polled every 15 minutes, so the door has already opened by the time
   ERPNext sees the event. It's a flag on the Employee Checkin
   (`flagged_anti_passback` / `flag_reason`, hidden custom fields) plus an
   audit log entry and an optional email to **Anti-Passback Alert
   Recipients**, for a human to review after the fact. True real-time
   blocking would need the device to push events instantly, which most
   standalone Hikvision terminals don't do without HikCentral.

2. **Biometric Visitor** doctype (`visitor_sync.py`) - temporary badges
   for non-employees. Unlike Employee (default-allow, opt-out), a Visitor
   is **default-deny**: empty `device_access` table means enrolled
   nowhere, on purpose. `Valid From`/`Valid To` drive an auto-expiry
   scheduled job (`expire_visitors`, every 15 min) that revokes them from
   every device once `Valid To` passes and marks status `Expired`. Form
   buttons: **Provision on Devices**, **Revoke Now**.

3. **Late arrival alerts** (`attendance_alerts.py`) - toggle in Settings
   (**Enable Late Arrival Alerts**, with a grace period). Uses HRMS's
   `Shift Assignment` doctype if installed, otherwise falls back to
   `Employee.default_shift`, so it works either way. Emails the
   employee's `Reports To` manager (or configured fallback recipients)
   **once per employee per day** - deduped via `Biometric Late Alert Log`
   - if no `Employee Checkin` (IN) exists by grace-period-past-shift-start.

4. **Bulk provisioning** (`bulk_operations.py`) - new **Bulk Actions**
   button group on the Biometric Device form: pick any number of
   employees via a multi-select dialog, enroll or revoke all of them on
   that device in one call, instead of one employee at a time.

5. **Device clock drift check** - extended `device_health.py`. Every
   10-minute health check now also reads each device's time via
   `/ISAPI/System/time`, computes drift against the ERPNext server, and
   alerts (**once**, on the in-sync→drifted transition, same pattern as
   the offline alert) past **Max Allowed Clock Drift (seconds)**. New
   `Biometric Device` fields: `Clock Drift (seconds)`, `Clock In Sync`.
   Matters because drift can throw off event ordering and the
   anti-passback cooldown window.

6. **"My Biometric Access" report** (Script Report, `Employee`/`HR User`/
   `HR Manager`/`System Manager` roles) - an employee running it sees
   only their own allowed/denied devices (resolved from their own
   `Employee.user_id`); HR/System Manager can look up anyone via the
   `employee` filter. Live device-enrollment probing (an HR/admin-weight
   action) is skipped for the plain self-service view so opening the
   report doesn't hit every device.

New doctypes this batch: `Biometric Visitor`, `Biometric Late Alert Log`.
New patch: `patches/v1_3/add_anti_passback_fields.py` (added as a *new*
patch rather than editing the already-shipped `v1_1`, since Frappe won't
re-run a patch it has already logged as executed on a site that migrated
before this update).

## Device-wise / location-wise entry restriction (new)

New doctypes: **Biometric Location** (optional grouping of devices - e.g.
"Building A – Main Gate" can span several door devices) and a new
**Biometric Access** tab on the Employee form (`patches/v1_2`, a Custom
Field table, no core Employee changes) where you list which devices or
locations that employee may enter, optionally with a date window
(`Valid From` / `Valid To` - handy for contractors).

**Default is unrestricted**: an employee with no rows in that table is
enrolled everywhere, exactly like before this feature existed - nothing
breaks or locks anyone out on upgrade.

Turn it on in **Biometric Field Mapping Settings → Enable Device-Wise
Access Control**. Once on, `sync_employee` (on save, or the manual
buttons) computes each employee's allowed device set and:
- **enrolls** them (UserInfo + saved face/fingerprint template) on every
  allowed device,
- **actively revokes** them (deletes the device-side user record) from
  every device they're *not* allowed at - not just "stops pushing," since
  a stale enrollment left behind is itself a security gap.

Employee form buttons: **Sync Device Access Now** (push the enroll/revoke
pass immediately) and **Check Access Status** (shows allowed/denied
without contacting any device).

**Known limitation**: while access control is on, the per-device push
only sets `employeeNo` + `name` (the minimum for enrollment) - it doesn't
apply your full custom field-mapping rows (e.g. department) the way the
unrestricted path does. If you need those extra fields pushed too while
access control is on, say so and I'll fold that in.

## Pushing this to GitHub

I don't have write access to your repo. From your machine:

```bash
cd biometric_integration          # your existing clone
git checkout -b multi-device-direct-sync
# copy the files from this delivery over the matching paths in your repo
git add -A
git commit -m "Multi-device direct Hikvision sync, Employee Checkin as single source of truth, mobile API, employee field mapping"
git push origin multi-device-direct-sync
# then open a PR, or merge to master yourself
```
