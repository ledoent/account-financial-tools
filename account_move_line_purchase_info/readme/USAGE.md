- **Purchase Order Tracking**: identify which accounting entries relate to specific purchase orders.
- **Audit & Compliance**: improve traceability from financial records back to procurement documents.
- **Financial Analysis**: analyze costs and expenses grouped by purchase orders.
- **Reconciliation**: ease the matching of vendor invoices with their corresponding purchase orders.

## What changed in 19.0

Odoo 19's standard stock valuation no longer uses interim accounts, so the
`purchase_line_id` field on `account.move.line` is already populated by core
for the journal entries this module previously had to enrich. The module
therefore no longer needs the `journal_entry_ids`, `account_move`
`purchase_line_id` override, or `stock_move` glue it carried in earlier
versions — those were removed during the 19.0 migration.

What remains in 19.0:

- The views that surface PO info on `account.move.line` (this is the
  primary user-visible feature).
- An optional `_compute_display_name` override on `purchase.order.line`
  that, when `po_line_info=True` is in the context, formats the line as
  `[<PO name>] <line name> (<state>)` — useful for places that show a
  line picker and want the originating PO visible at a glance.
