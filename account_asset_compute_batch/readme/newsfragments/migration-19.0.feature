Migrated to Odoo 19.0.

The ``_sql_constraints`` list on ``account.asset.compute.batch`` was
converted to the new ``models.Constraint`` class attribute API (Odoo 19
removed the legacy ``_sql_constraints`` mechanism).
