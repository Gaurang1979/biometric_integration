// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

// Highlights manually-created or manually-edited Employee Checkins in red,
// so HR can see at a glance which entries reconciliation will never touch.
// See checkin_hooks.py for how custom_entry_type / custom_manually_modified
// get set.

frappe.ui.form.on("Employee Checkin", {
	refresh(frm) {
		if (frm.is_new()) return;

		const is_manual = frm.doc.custom_entry_type === "Manual";
		const is_modified = !!frm.doc.custom_manually_modified;

		if (is_manual || is_modified) {
			frm.dashboard.add_comment(
				is_manual
					? __("Manually created - will never be changed by biometric reconciliation.")
					: __("Manually modified after being auto-generated - will never be overwritten by biometric reconciliation."),
				"red",
				true
			);

			["time", "log_type"].forEach((fieldname) => {
				const field = frm.get_field(fieldname);
				if (field && field.$wrapper) {
					field.$wrapper.css({
						"border": "1px solid var(--red-500, #e24c4c)",
						"border-radius": "var(--border-radius-md, 6px)",
						"padding": "2px 4px",
					});
				}
			});
		}
	},
});

// List view: mark manual / manually-modified rows red without clobbering
// HRMS's own indicator logic for this doctype if it already defined one.
frappe.listview_settings = frappe.listview_settings || {};
(function () {
	const existing = frappe.listview_settings["Employee Checkin"];
	const base_indicator = existing && existing.get_indicator;

	frappe.listview_settings["Employee Checkin"] = Object.assign({}, existing, {
		get_indicator(doc) {
			if (doc.custom_entry_type === "Manual" || doc.custom_manually_modified) {
				return [__("Manual"), "red", "custom_entry_type,=,Manual"];
			}
			if (base_indicator) return base_indicator(doc);
			return [__(doc.log_type || ""), "blue", "log_type,=," + (doc.log_type || "")];
		},
	});
})();
