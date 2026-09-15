# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

"""Visitor Management was removed from this app entirely (2026-09-14) - see
v1_6's cleanup counterpart for the actual doctype deletion. This patch is
kept (rather than deleted) only because it may have already run and been
recorded in Patch Log on sites that migrated between the two changes;
leaving a no-op here avoids Frappe complaining about a missing patch module
for an already-applied patch."""

import frappe


def execute():
	return
