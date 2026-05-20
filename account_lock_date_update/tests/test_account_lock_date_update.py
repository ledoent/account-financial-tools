# Copyright 2017 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import Command, fields
from odoo.exceptions import AccessError, RedirectWarning
from odoo.tests.common import TransactionCase


class TestAccountLockDateUpdate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(
            context=dict(
                cls.env.context,
                mail_create_nolog=True,
                mail_create_nosubscribe=True,
                mail_notrack=True,
                no_reset_password=True,
                tracking_disable=True,
            )
        )
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.ref("base.main_company")
        cls.demo_user = cls.env["res.users"].create(
            {
                "name": "Test User",
                "login": "test_user_unique",
                "email": "test@example.com",
                "group_ids": [Command.link(cls.env.ref("base.group_user").id)],
            }
        )
        cls.adviser_group = cls.env.ref("account.group_account_manager")
        cls.bank_journal = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1
        )

    def _make_wizard(self, vals=None):
        self.demo_user.write({"group_ids": [Command.link(self.adviser_group.id)]})
        wizard = (
            self.env["account.update.lock_date"]
            .with_user(self.demo_user.id)
            .create({"company_id": self.company.id})
        )
        if vals:
            wizard.write(vals)
        return wizard

    def test_01_update_without_access(self):
        self.demo_user.write({"group_ids": [Command.unlink(self.adviser_group.id)]})
        with self.assertRaises(AccessError):
            self.env["account.update.lock_date"].with_user(self.demo_user.id).create(
                {"company_id": self.company.id}
            )

    def test_02_update_with_access(self):
        wizard = self._make_wizard(
            {
                "sale_lock_date": "2000-05-01",
                "purchase_lock_date": "2000-04-01",
                "tax_lock_date": "2000-03-01",
                "fiscalyear_lock_date": "2000-02-01",
                "hard_lock_date": "2000-01-01",
            }
        )
        wizard.with_user(self.demo_user.id).execute()
        self.assertEqual(
            fields.Date.to_string(self.company.sale_lock_date), "2000-05-01"
        )
        self.assertEqual(
            fields.Date.to_string(self.company.purchase_lock_date), "2000-04-01"
        )
        self.assertEqual(
            fields.Date.to_string(self.company.tax_lock_date), "2000-03-01"
        )
        self.assertEqual(
            fields.Date.to_string(self.company.fiscalyear_lock_date), "2000-02-01"
        )
        self.assertEqual(
            fields.Date.to_string(self.company.hard_lock_date), "2000-01-01"
        )

    def test_03_unreconciled_lines_redirect_to_account_move(self):
        """RedirectWarning for unreconciled entries must point to account.move, not
        account.bank.statement.line (which has no standalone views in Odoo 19 core)."""
        stmt_line = self.env["account.bank.statement.line"].create(
            {
                "journal_id": self.bank_journal.id,
                "date": "2000-01-15",
                "payment_ref": "unreconciled_test",
                "amount": 100.0,
            }
        )
        self.assertFalse(stmt_line.is_reconciled)
        wizard = self._make_wizard({"fiscalyear_lock_date": "2000-06-30"})
        with self.assertRaises(RedirectWarning) as ctx:
            wizard.with_user(self.demo_user.id).execute()
        action = ctx.exception.args[1]
        self.assertEqual(
            action.get("res_model"),
            "account.move",
            "Redirect must point to account.move, not account.bank.statement.line",
        )
        # The redirected move must be the one backing the unreconciled statement line
        if action.get("res_id"):
            self.assertEqual(action["res_id"], stmt_line.move_id.id)
        else:
            self.assertIn(stmt_line.move_id.id, action.get("domain", [[]])[0][2])

    def test_04_two_unreconciled_lines_redirect_domain(self):
        """Multiple unreconciled lines: redirect must use domain on account.move."""
        lines = self.env["account.bank.statement.line"].create(
            [
                {
                    "journal_id": self.bank_journal.id,
                    "date": "2000-02-01",
                    "payment_ref": "unrec_a",
                    "amount": 10.0,
                },
                {
                    "journal_id": self.bank_journal.id,
                    "date": "2000-02-02",
                    "payment_ref": "unrec_b",
                    "amount": 20.0,
                },
            ]
        )
        self.assertFalse(any(lines.mapped("is_reconciled")))
        wizard = self._make_wizard({"fiscalyear_lock_date": "2000-06-30"})
        with self.assertRaises(RedirectWarning) as ctx:
            wizard.with_user(self.demo_user.id).execute()
        action = ctx.exception.args[1]
        self.assertEqual(action.get("res_model"), "account.move")
        self.assertFalse(
            action.get("res_id"), "Multi-line redirect must use domain, not res_id"
        )
        domain_ids = action.get("domain", [[]])[0][2]
        for line in lines:
            self.assertIn(line.move_id.id, domain_ids)

    def test_05_no_unreconciled_lines_succeeds(self):
        """execute() must succeed when there are no unreconciled bank statement lines
        in the period. Uses a far-past date guaranteed to be clean."""
        wizard = self._make_wizard({"fiscalyear_lock_date": "1990-12-31"})
        # No bank statement lines exist before 1990 — should not raise
        wizard.with_user(self.demo_user.id).execute()
        self.assertEqual(
            fields.Date.to_string(self.company.fiscalyear_lock_date), "1990-12-31"
        )
