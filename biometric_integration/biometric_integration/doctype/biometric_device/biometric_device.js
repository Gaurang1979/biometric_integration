// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on("Biometric Device", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.test_connection",
				args: { device_name: frm.doc.name },
				freeze: true,
				callback: (r) => {
					const indicator = r.message?.status === "success" ? "green" : "red";
					frappe.msgprint({ message: r.message?.message, indicator });
				},
			});
		}, __("Device"));

		frm.add_custom_button(__("Sync Now"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Sync Attendance From This Device"),
				fields: [
					{ label: __("From"), fieldname: "from_datetime", fieldtype: "Datetime" },
					{ label: __("To"), fieldname: "to_datetime", fieldtype: "Datetime" },
				],
				primary_action_label: __("Sync"),
				primary_action(values) {
					d.hide();
					frappe.call({
						method: "biometric_integration.biometric_integration.device_sync.sync_device",
						args: { device_name: frm.doc.name, ...values },
						freeze: true,
						freeze_message: __("Syncing..."),
						callback: (r) => {
							frappe.show_alert({ message: JSON.stringify(r.message), indicator: "green" }, 10);
							frm.reload_doc();
						},
					});
				},
			});
			d.show();
		}, __("Device"));

		frm.add_custom_button(__("View Face"), () => {
			frappe.prompt(
				[{ label: "Employee No (on device)", fieldname: "emp_no", fieldtype: "Data", reqd: 1 }],
				(values) => {
					frappe.call({
						method: "biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.get_employee_face",
						args: { device_name: frm.doc.name, emp_no: values.emp_no },
						freeze: true,
						callback: (r) => {
							if (r.message?.status === "success") {
								const src = r.message.type === "base64"
									? `data:image/jpeg;base64,${r.message.data}`
									: r.message.data;
								frappe.msgprint({
									title: __("Employee Face"),
									message: `<img src="${src}" style="max-width:100%;">`,
								});
							} else {
								frappe.msgprint({ message: r.message?.message, indicator: "red" });
							}
						},
					});
				},
				__("Enter Employee No"),
				__("Fetch")
			);
		}, __("Device"));

		frm.add_custom_button(__("Update Employee Name"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Set Employee Name on Device"),
				fields: [
					{ label: __("Employee No (Device)"), fieldname: "emp_no", fieldtype: "Data", reqd: 1 },
					{ label: __("Employee Name"), fieldname: "emp_name", fieldtype: "Data" },
				],
				primary_action_label: __("Save"),
				primary_action(values) {
					d.hide();
					frappe.call({
						method: "biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.set_employee_name_on_device",
						args: { device_name: frm.doc.name, emp_no: values.emp_no, emp_name: values.emp_name },
						freeze: true,
						callback: (r) => {
							const indicator = r.message?.status === "success" ? "green" : "red";
							frappe.msgprint({ message: r.message?.message, indicator });
						},
					});
				},
			});
			d.show();
		}, __("Device"));

		frm.add_custom_button(__("Bulk Enroll Employees"), () => {
			open_bulk_dialog(frm, "enroll");
		}, __("Bulk Actions"));

		frm.add_custom_button(__("Bulk Revoke Employees"), () => {
			open_bulk_dialog(frm, "revoke");
		}, __("Bulk Actions"));
	},
});

function open_bulk_dialog(frm, action) {
	const d = new frappe.ui.Dialog({
		title: action === "enroll" ? __("Bulk Enroll on This Device") : __("Bulk Revoke From This Device"),
		fields: [
			{
				label: __("Employees"),
				fieldname: "employees",
				fieldtype: "MultiSelectList",
				get_data: function (txt) {
					return frappe.db.get_link_options("Employee", txt, { status: "Active" });
				},
				reqd: 1,
			},
		],
		primary_action_label: action === "enroll" ? __("Enroll") : __("Revoke"),
		primary_action(values) {
			d.hide();
			frappe.call({
				method: "biometric_integration.biometric_integration.bulk_operations.bulk_sync_access",
				args: { employees: values.employees, device_name: frm.doc.name, action },
				freeze: true,
				freeze_message: __("Processing {0} employees...", [values.employees.length]),
				callback: (r) => {
					const rows = Object.entries(r.message?.results || {})
						.map(([emp, res]) => {
							const summary = Object.values(res)[0]?.status || res.message || "-";
							const ok = Object.values(res).every((x) => x.status === "success");
							return `<tr><td>${frappe.utils.escape_html(emp)}</td><td>${ok ? "✅" : "❌"} ${frappe.utils.escape_html(JSON.stringify(res))}</td></tr>`;
						})
						.join("");
					frappe.msgprint({
						title: __("Bulk {0} Result", [action]),
						message: `<table class="table table-bordered"><tr><th>${__("Employee")}</th><th>${__("Result")}</th></tr>${rows}</table>`,
						wide: true,
					});
				},
			});
		},
	});
	d.show();
}
