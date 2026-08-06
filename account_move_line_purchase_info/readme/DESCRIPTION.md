This module surfaces purchase-order information directly on `account.move.line`
(journal items), improving traceability between accounting entries and their
originating purchase orders.

## Scope in 19.0

This is a deliberately small module in 19.0 — substantially simpler than the
18.0 version. Odoo 19's standard stock valuation no longer uses interim
accounts and now fills `account.move.line.purchase_line_id` correctly out of
the box, so the model fields and stock-move glue this module previously
provided are no longer needed and were removed during the 19.0 migration. The
module now contributes:

- The view inheritance that displays PO information on `account.move.line`
  (its core user-facing purpose).
- An optional `_compute_display_name` override on `purchase.order.line`,
  activated by a `po_line_info=True` context key.

See the `[MIG]` commit and PR description for the full refactor history.
