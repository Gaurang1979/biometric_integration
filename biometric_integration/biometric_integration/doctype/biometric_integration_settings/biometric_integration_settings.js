frappe.ui.form.on("Biometric Integration Settings", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("Test All Devices"), () => {
            frappe.call({
                method: "biometric_integration.biometric_integration.hikvision.test_all_devices",
                freeze: true,
                freeze_message: __("Testing Hikvision devices...")
            }).then(r => {
                if (r.message) {
                    frappe.msgprint({
                        title: __("Device Test"),
                        message: `<pre>${frappe.utils.escape_html(JSON.stringify(r.message, null, 2))}</pre>`
                    });
                }
            });
        });

        const devices = (frm.doc.devices || []).filter(row => row.enabled);

        frm.add_custom_button(__("Import Attendance"), () => {
            if (!devices.length) {
                return frappe.msgprint(__("Add at least one enabled Hikvision device first."));
            }

            const d = new frappe.ui.Dialog({
                title: __("Import Hikvision Attendance"),
                fields: [
                    {
                        fieldname: "from_datetime",
                        label: __("From"),
                        fieldtype: "Datetime",
                        reqd: 1,
                        default: frappe.datetime.add_days(
                            frappe.datetime.now_datetime(),
                            -1
                        )
                    },
                    {
                        fieldname: "to_datetime",
                        label: __("To"),
                        fieldtype: "Datetime",
                        reqd: 1,
                        default: frappe.datetime.now_datetime()
                    }
                ],
                primary_action_label: __("Import"),
                primary_action(values) {
                    frappe.call({
                        method: "biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings.sync_attendance",
                        args: {
                            from_datetime: values.from_datetime,
                            to_datetime: values.to_datetime
                        },
                        freeze: true,
                        freeze_message: __("Fetching and creating Employee Checkins from all Hikvision devices...")
                    }).then(r => {
                        if (r.message) {
                            frappe.msgprint({
                                title: __("Import Result"),
                                message: `<pre>${frappe.utils.escape_html(JSON.stringify(r.message, null, 2))}</pre>`
                            });
                        }
                        d.hide();
                    }).catch(() => {
                        d.hide();
                    });
                }
            });

            d.show();
        });

        frm.add_custom_button(__("Fetch All Device Info"), () => {
            if (!devices.length) {
                return frappe.msgprint(__("Add an enabled Hikvision device first."));
            }

            frappe.call({
                method: "biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings.fetch_all_device_info",
                freeze: true,
                freeze_message: __("Reading information from all enabled Hikvision devices...")
            }).then(r => {
                const result = r.message || {};
                const rows = result.devices || [];

                if (!rows.length) {
                    frappe.msgprint(__("No enabled devices were found."));
                    return;
                }

                const message = rows.map(row => {
                    const label = frappe.utils.escape_html(
                        row.device_name || row.name || "Device"
                    );
                    const status = row.status === "success" ? "✓" : "✗";
                    const detail = row.status === "success"
                        ? `${frappe.utils.escape_html(row.model || "")} | ${frappe.utils.escape_html(row.serial_number || "")}`
                        : frappe.utils.escape_html(row.message || "Unknown error");

                    return `<div><b>${status} ${label}</b><br>${detail}</div>`;
                }).join("<hr>");

                frappe.msgprint({
                    title: __("Device Information"),
                    message
                });

                frm.reload_doc();
            });
        });
    }
});
