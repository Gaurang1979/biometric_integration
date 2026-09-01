frappe.ui.form.on("Biometric Integration Settings", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("Test All Devices"), () => {
            frappe.call({
                method: "biometric_integration.biometric_integration.hikvision.test_all_devices",
                freeze: true,
                freeze_message: __("Testing Hikvision devices...")
            }).then(r => {
                if (r.message) frappe.msgprint({title: __("Device Test"), message: `<pre>${frappe.utils.escape_html(JSON.stringify(r.message, null, 2))}</pre>`});
            });
        });

        const devices = (frm.doc.devices || []).filter(row => row.enabled);
        frm.add_custom_button(__("Import Attendance"), () => {
            if (!devices.length) return frappe.msgprint(__("Add at least one enabled Hikvision device first."));
            const options = devices.map(row => ({label: row.device_name || row.ip, value: row.name}));
            const d = new frappe.ui.Dialog({
                title: __("Import Hikvision Attendance"),
                fields: [
                    {fieldname: "device", label: __("Device"), fieldtype: "Select", options, reqd: 1},
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
            if (!devices.length) return frappe.msgprint(__("Add an enabled Hikvision device first."));
            const row = devices[0];
            frappe.call({
                method: "biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings.fetch_device_info",
                args: {device_name: row.name},
                freeze: true,
                freeze_message: __("Reading device information...")
            }).then(() => frm.reload_doc());
        });
    }
});
