// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on("Biometric Visitor", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("Provision on Devices"), () => {
				frappe.call({
					method: "biometric_integration.biometric_integration.visitor_sync.provision_visitor",
					args: { visitor: frm.doc.name },
					freeze: true,
					freeze_message: __("Provisioning visitor..."),
					callback: (r) => {
						frm.reload_doc();
						frappe.msgprint({
							title: __("Provisioning Result"),
							message: (r.message?.log || []).join("<br>") || r.message?.message,
						});
					},
				});
			});

			frm.add_custom_button(__("Revoke Now"), () => {
				frappe.confirm(__("Revoke this visitor from all devices?"), () => {
					frappe.call({
						method: "biometric_integration.biometric_integration.visitor_sync.revoke_visitor",
						args: { visitor: frm.doc.name },
						freeze: true,
						callback: (r) => {
							frm.reload_doc();
							frappe.msgprint({
								title: __("Revocation Result"),
								message: (r.message?.log || []).join("<br>"),
							});
						},
					});
				});
			});
		}
	},
});
