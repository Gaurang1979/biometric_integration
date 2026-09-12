// Copyright (c) 2025, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on('Biometric Integration Settings', {
	validate(frm) {
		if (frm.doc.enable_biometric_attendance_log_deletion) {
			if (!frm.doc.delete_logs_after_days || frm.doc.delete_logs_after_days <= 0) {
				frappe.throw("Delete Logs After (Days) must be greater than 0");
			}
		}
	},
});
