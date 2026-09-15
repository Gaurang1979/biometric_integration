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

	refresh(frm) {
		// Devices moved here (2026-09-14) from their own standalone doctype -
		// these were per-document buttons on Biometric Device itself; a
		// child-table row dialog doesn't render page-level buttons, so they
		// all live on the grid toolbar instead and act on the selected row.
		const grid = frm.fields_dict.devices && frm.fields_dict.devices.grid;
		if (!grid) return;

		function selected_device(single) {
			const rows = grid.get_selected_children();
			if (!rows.length) {
				frappe.msgprint(__("Select a device row first."));
				return null;
			}
			if (single && rows.length > 1) {
				frappe.msgprint(__("Select only one device row for this action."));
				return null;
			}
			return rows;
		}

		grid.add_custom_button(__("Test Connection"), () => {
			const rows = selected_device();
			if (!rows) return;
			rows.forEach((row) => {
				frappe.call({
					method: "biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.test_connection",
					args: { device_name: row.name },
					freeze: true,
					callback: (r) => {
						const indicator = r.message?.status === "success" ? "green" : "red";
						frappe.msgprint({ message: `${row.device_name}: ${r.message?.message}`, indicator });
					},
				});
			});
		});

		grid.add_custom_button(__("Sync Now"), () => {
			const rows = selected_device();
			if (!rows) return;
			const d = new frappe.ui.Dialog({
				title: __("Sync Attendance From Selected Device(s)"),
				fields: [
					{ label: __("From"), fieldname: "from_datetime", fieldtype: "Datetime" },
					{ label: __("To"), fieldname: "to_datetime", fieldtype: "Datetime" },
				],
				primary_action_label: __("Sync"),
				primary_action(values) {
					d.hide();
					rows.forEach((row) => {
						frappe.call({
							method: "biometric_integration.biometric_integration.device_sync.sync_device",
							args: { device_name: row.name, ...values },
							freeze: true,
							freeze_message: __("Syncing..."),
							callback: (r) => {
								frappe.show_alert({ message: `${row.device_name}: ${JSON.stringify(r.message)}`, indicator: "green" }, 10);
								frm.reload_doc();
							},
						});
					});
				},
			});
			d.show();
		});

		grid.add_custom_button(__("View Face"), () => {
			const rows = selected_device(true);
			if (!rows) return;
			const device_name = rows[0].name;
			frappe.prompt(
				[{ label: "Employee No (on device)", fieldname: "emp_no", fieldtype: "Data", reqd: 1 }],
				(values) => {
					frappe.call({
						method: "biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.get_employee_face",
						args: { device_name, emp_no: values.emp_no },
						freeze: true,
						callback: (r) => {
							if (r.message?.status === "success") {
								const src = r.message.type === "base64"
									? `data:image/jpeg;base64,${r.message.data}`
									: r.message.data;
								frappe.msgprint({ title: __("Employee Face"), message: `<img src="${src}" style="max-width:100%;">` });
							} else {
								frappe.msgprint({ message: r.message?.message, indicator: "red" });
							}
						},
					});
				},
				__("Enter Employee No"),
				__("Fetch")
			);
		});

		grid.add_custom_button(__("Update Employee Name"), () => {
			const rows = selected_device(true);
			if (!rows) return;
			const device_name = rows[0].name;
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
						args: { device_name, emp_no: values.emp_no, emp_name: values.emp_name },
						freeze: true,
						callback: (r) => {
							const indicator = r.message?.status === "success" ? "green" : "red";
							frappe.msgprint({ message: r.message?.message, indicator });
						},
					});
				},
			});
			d.show();
		});

		grid.add_custom_button(__("Bulk Enroll Employees"), () => {
			const rows = selected_device(true);
			if (rows) open_bulk_dialog(rows[0].name, "enroll");
		});

		grid.add_custom_button(__("Bulk Revoke Employees"), () => {
			const rows = selected_device(true);
			if (rows) open_bulk_dialog(rows[0].name, "revoke");
		});
	},
});

function open_bulk_dialog(device_name, action) {
	const d = new frappe.ui.Dialog({
		title: action === "enroll" ? __("Bulk Enroll on Selected Device") : __("Bulk Revoke From Selected Device"),
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
				args: { employees: values.employees, device_name, action },
				freeze: true,
				freeze_message: __("Processing {0} employees...", [values.employees.length]),
				callback: (r) => {
					const rows = Object.entries(r.message?.results || {})
						.map(([emp, res]) => {
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
