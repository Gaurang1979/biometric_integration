// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

// Adds a "Biometric" button group directly on the Employee form so HR can
// manage devices without touching HikCentral or the Biometric Device list.
//
// Note: Employee's standard "image" field already has a webcam-capture
// option built into its upload dialog (click the image placeholder ->
// the upload dialog has a "Capture" tab). We don't need to build a
// separate capture widget for that - just point people at it.

frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Pull From Device \u0026 Replicate to All"), () => {
			get_device_list().then((devices) => {
				if (!devices.length) {
					frappe.msgprint(__("No enabled Biometric Device found."));
					return;
				}
				if (!frm.doc.attendance_device_id) {
					frappe.msgprint(__("Set Attendance Device ID first."));
					return;
				}
				frappe.prompt(
					[
						{
							label: __("Device Where Employee Just Enrolled"),
							fieldname: "source_device",
							fieldtype: "Select",
							options: devices,
							reqd: 1,
						},
						{ label: __("Pull Face"), fieldname: "include_face", fieldtype: "Check", default: 1 },
						{
							label: __("Pull Fingerprint (experimental)"),
							fieldname: "include_fingerprint",
							fieldtype: "Check",
							default: 1,
						},
					],
					(values) => {
						frappe.call({
							method: "biometric_integration.biometric_integration.biometric_enrollment.pull_and_replicate",
							args: {
								employee: frm.doc.name,
								source_device: values.source_device,
								include_face: values.include_face,
								include_fingerprint: values.include_fingerprint,
							},
							freeze: true,
							freeze_message: __("Pulling from device and replicating to others..."),
							callback: (r) => {
								show_replication_result(r.message);
							},
						});
					},
					__("Replicate Biometrics"),
					__("Pull \u0026 Replicate")
				);
			});
		}, __("Biometric"));

		frm.add_custom_button(__("Push Saved Template to All Devices"), () => {
			frappe.call({
				method: "biometric_integration.biometric_integration.biometric_enrollment.push_saved_template_to_devices",
				args: { employee: frm.doc.name },
				freeze: true,
				freeze_message: __("Pushing saved template..."),
				callback: (r) => {
					if (r.message?.status === "error") {
						frappe.msgprint(r.message.message);
						return;
					}
					show_replication_result({ push_result: r.message });
				},
			});
		}, __("Biometric"));

		frm.add_custom_button(__("Enroll Face on Devices"), () => {
			if (!frm.doc.image) {
				frappe.msgprint(__("Upload a photo first - click the employee photo placeholder, then use Capture or Upload."));
				return;
			}
			if (!frm.doc.attendance_device_id) {
				frappe.msgprint(__("Set Attendance Device ID first - this is the employee number used on the devices."));
				return;
			}
			frappe.call({
				method: "biometric_integration.biometric_integration.biometric_enrollment.enroll_face",
				args: { employee: frm.doc.name },
				freeze: true,
				freeze_message: __("Pushing photo to devices..."),
				callback: (r) => {
					show_multi_device_result(r.message?.results);
				},
			});
		}, __("Biometric"));

		frm.add_custom_button(__("Enroll Fingerprint (Experimental)"), () => {
			get_device_list().then((devices) => {
				if (!devices.length) {
					frappe.msgprint(__("No enabled Biometric Device found."));
					return;
				}
				frappe.prompt(
					[
						{
							label: __("Device"),
							fieldname: "device_name",
							fieldtype: "Select",
							options: devices,
							reqd: 1,
						},
					],
					(values) => {
						frappe.call({
							method: "biometric_integration.biometric_integration.biometric_enrollment.trigger_fingerprint_capture",
							args: { employee: frm.doc.name, device_name: values.device_name },
							freeze: true,
							freeze_message: __("Contacting device..."),
							callback: (r) => {
								const indicator = r.message?.status === "success" ? "green" : "orange";
								frappe.msgprint({ title: __("Fingerprint Capture"), message: r.message?.message, indicator });
							},
						});
					},
					__("Select Device"),
					__("Start Capture")
				);
			});
		}, __("Biometric"));

		frm.add_custom_button(__("Sync to Devices Now"), () => {
			frappe.call({
				method: "biometric_integration.biometric_integration.employee_sync.sync_employee",
				args: { employee: frm.doc.name },
				freeze: true,
				freeze_message: __("Syncing employee to devices/mobile..."),
				callback: () => {
					frappe.show_alert({ message: __("Sync triggered - check device Sync log / mobile webhook for results."), indicator: "green" }, 6);
				},
			});
		}, __("Biometric"));

		frm.add_custom_button(__("Check Enrollment Status"), () => {
			if (!frm.doc.attendance_device_id) {
				frappe.msgprint(__("Set Attendance Device ID first."));
				return;
			}
			frappe.call({
				method: "biometric_integration.biometric_integration.biometric_enrollment.check_enrollment_status",
				args: { employee: frm.doc.name },
				freeze: true,
				callback: (r) => {
					show_status_result(r.message?.results);
				},
			});
		}, __("Biometric"));

		frm.add_custom_button(__("Sync Device Access Now"), () => {
			if (!frm.doc.attendance_device_id) {
				frappe.msgprint(__("Set Attendance Device ID first."));
				return;
			}
			frappe.call({
				method: "biometric_integration.biometric_integration.access_control.sync_employee_access",
				args: { employee: frm.doc.name },
				freeze: true,
				freeze_message: __("Syncing device access (enroll allowed, revoke denied)..."),
				callback: (r) => {
					show_access_sync_result(r.message);
				},
			});
		}, __("Access Control"));

		frm.add_custom_button(__("Check Access Status"), () => {
			frappe.call({
				method: "biometric_integration.biometric_integration.access_control.check_access_summary",
				args: { employee: frm.doc.name },
				freeze: true,
				callback: (r) => {
					show_access_summary(r.message);
				},
			});
		}, __("Access Control"));
	},
});

function show_access_sync_result(message) {
	if (!message || message.status === "error") {
		frappe.msgprint(message?.message || __("No response."));
		return;
	}
	const rows = message.results || {};
	const fmt = (obj) =>
		Object.entries(obj || {})
			.map(([device, res]) => {
				const parts = Object.entries(res)
					.map(([kind, r]) => `${kind}: ${r.status === "success" ? "✅" : "❌ " + frappe.utils.escape_html(r.message || "")}`)
					.join("<br>");
				return `<tr><td>${frappe.utils.escape_html(device)}</td><td>${parts || (res.status === "success" ? "✅" : "❌ " + frappe.utils.escape_html(res.message || ""))}</td></tr>`;
			})
			.join("");

	const html = `
		<p><b>${__("Enrolled on")} (${message.allowed_count}):</b></p>
		<table class="table table-bordered"><tr><th>${__("Device")}</th><th>${__("Result")}</th></tr>${fmt(rows.enrolled)}</table>
		<p><b>${__("Revoked from")} (${message.denied_count}):</b></p>
		<table class="table table-bordered"><tr><th>${__("Device")}</th><th>${__("Result")}</th></tr>${fmt(rows.revoked)}</table>
	`;
	frappe.msgprint({ title: __("Device Access Sync Result"), message: html, wide: true });
}

function show_access_summary(message) {
	if (!message) {
		frappe.msgprint(__("No response."));
		return;
	}
	const note =
		message.status === "unrestricted"
			? __("No access rules set - unrestricted (enrolled on every enabled device).")
			: __("Restricted - see allowed/denied below.");
	frappe.msgprint({
		title: __("Access Status"),
		message: `<p>${note}</p><p><b>${__("Allowed")}:</b> ${message.allowed.join(", ") || "-"}</p><p><b>${__("Denied")}:</b> ${message.denied.join(", ") || "-"}</p>`,
	});
}

function get_device_list() {
	return frappe.db.get_list("Biometric Device", { filters: { enabled: 1 }, fields: ["name"], limit: 100 }).then((rows) => rows.map((d) => d.name));
}

function show_replication_result(message) {
	let html = "";
	if (message?.pull_log) {
		html += `<p><b>${__("Pulled from source device")}:</b></p><ul>${message.pull_log.map((l) => `<li>${frappe.utils.escape_html(l)}</li>`).join("")}</ul>`;
	}
	const push = message?.push_result;
	if (push?.results) {
		let rows = Object.entries(push.results)
			.map(([device, res]) => {
				const parts = Object.entries(res)
					.map(([kind, r]) => `${kind}: ${r.status === "success" ? "✅" : "❌ " + frappe.utils.escape_html(r.message || "")}`)
					.join("<br>");
				return `<tr><td>${frappe.utils.escape_html(device)}</td><td>${parts || "-"}</td></tr>`;
			})
			.join("");
		html += `<p><b>${__("Pushed to other devices")}:</b></p><table class="table table-bordered"><tr><th>${__("Device")}</th><th>${__("Result")}</th></tr>${rows}</table>`;
	}
	frappe.msgprint({ title: __("Biometric Replication Result"), message: html || __("No result."), wide: true });
}

function show_multi_device_result(results) {
	if (!results) {
		frappe.msgprint(__("No response from devices."));
		return;
	}
	let rows = Object.entries(results)
		.map(([device, res]) => `<tr><td>${frappe.utils.escape_html(device)}</td><td>${res.status === "success" ? "✅" : "❌"} ${frappe.utils.escape_html(res.message || "")}</td></tr>`)
		.join("");
	frappe.msgprint({
		title: __("Face Enrollment Result"),
		message: `<table class="table table-bordered"><tr><th>${__("Device")}</th><th>${__("Result")}</th></tr>${rows}</table>`,
	});
}

function show_status_result(results) {
	if (!results) {
		frappe.msgprint(__("No response from devices."));
		return;
	}
	let rows = Object.entries(results)
		.map(([device, res]) => {
			const enrolled = res.enrolled ? "✅ Enrolled" : "❌ Not enrolled";
			const face = res.has_face ? ", face on file" : res.enrolled ? ", no face on file" : "";
			return `<tr><td>${frappe.utils.escape_html(device)}</td><td>${enrolled}${face}</td></tr>`;
		})
		.join("");
	frappe.msgprint({
		title: __("Device Enrollment Status"),
		message: `<table class="table table-bordered"><tr><th>${__("Device")}</th><th>${__("Status")}</th></tr>${rows}</table>`,
	});
}
