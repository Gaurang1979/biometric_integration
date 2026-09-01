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
                    frappe.msgprint({title: __("Device Test"), message: `<pre>${frappe.utils.escape_html(JSON.stringify(r.message, null, 2))}</pre>`});
                }
            });
        });

        frm.add_custom_button(__("Import Attendance"), () => {
            const d = new frappe.ui.Dialog({
                title: __("Import Hikvision Attendance"),
                fields: [
                    {fieldname: "device", label: __("Device"), fieldtype: "Link", options: "Biometric Device", reqd: 1},
                    {fieldname: "from_datetime", label: __("From"), fieldtype: "Datetime", reqd: 1, default: frappe.datetime.add_days(frappe.datetime.now_datetime(), -1)},
                    {fieldname: "to_datetime", label: __("To"), fieldtype: "Datetime", reqd: 1, default: frappe.datetime.now_datetime()}
                ],
                primary_action_label: __("Import"),
                primary_action(values) {
                    frappe.call({
                        method: "biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings.sync_attendance",
                        args: values,
                        freeze: true,
                        freeze_message: __("Fetching and creating Employee Checkins...")
                    }).then(r => {
                        if (r.message) frappe.msgprint({title: __("Import Result"), message: `<pre>${frappe.utils.escape_html(JSON.stringify(r.message, null, 2))}</pre>`});
                        d.hide();
                    });
                }
            });
            d.show();
        });

        frm.add_custom_button(__("Fetch Device Info"), () => {
            const row = frm.doc.devices && frm.doc.devices[0];
            if (!row) return frappe.msgprint(__("Add a Hikvision device first."));
            frappe.call({
                method: "biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings.fetch_device_info",
                args: {device_name: row.name},
                freeze: true,
                freeze_message: __("Reading device information...")
            }).then(() => frm.reload_doc());
        });
    }
});

frappe.ui.form.on("Biometric Device", {
    form_render(frm, cdt, cdn) {
        // Child-row editing is intentionally simple; connection tests are available from the parent.
    }
});
