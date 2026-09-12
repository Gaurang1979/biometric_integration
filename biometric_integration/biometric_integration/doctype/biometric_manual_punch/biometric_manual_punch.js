// Copyright (c) 2025, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on('Biometric Manual Punch', {
	refresh(frm) {
		frm.set_df_property('punch_time', 'read_only', !frm.is_new());
		frm.set_df_property('punch_date', 'read_only', !frm.is_new());

		if (frm.is_new()) return;

		frm.add_custom_button(__('Edit Date & Time'), function () {
			frappe.prompt(
				[
					{
						label: 'New Punch Date',
						fieldname: 'new_punch_date',
						fieldtype: 'Date',
						reqd: 1,
						default: frm.doc.punch_date,
					},
					{
						label: 'New Punch Time',
						fieldname: 'new_punch_time',
						fieldtype: 'Time',
						reqd: 1,
						default: frm.doc.punch_time,
					},
				],
				function (values) {
					frappe.call({
						method: 'biometric_integration.biometric_integration.doctype.biometric_manual_punch.biometric_manual_punch.edit_manual_punch',
						args: {
							doc_name: frm.doc.name,
							new_punch_date: values.new_punch_date,
							new_punch_time: values.new_punch_time,
						},
						freeze: true,
						callback: function (r) {
							if (r.message && r.message.status === 'success') {
								frm.reload_doc();
								frappe.show_alert({ message: r.message.message, indicator: 'green' }, 5);
							} else {
								frappe.msgprint(r.message?.message || __('Failed to update the manual punch.'));
							}
						},
					});
				},
				__('Edit Punch Date & Time'),
				__('Update')
			);
		});
	},
});
