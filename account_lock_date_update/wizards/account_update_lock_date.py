# Copyright 2017 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.tools.misc import format_date

from odoo.addons.account.models.company import LOCK_DATE_FIELDS


class AccountUpdateLockDate(models.TransientModel):
    _name = "account.update.lock_date"
    _description = "Wizard to Update Accounting Lock Dates"

    company_id = fields.Many2one(comodel_name="res.company", required=True)
    fiscalyear_lock_date = fields.Date(
        string="Global Lock Date",
        help="Impossible to edit/create journal entries prior to and "
        "inclusive of this date. Subject to exceptions.",
    )
    tax_lock_date = fields.Date(
        string="Tax Return Lock Date",
        help="Impossible to edit/create journal entries related to a tax prior and "
        "inclusive of this date. Subject to exceptions.",
    )
    sale_lock_date = fields.Date(
        help="Impossible to edit/create sale journal entries prior to and "
        "inclusive of this date. Subject to exceptions.",
    )
    purchase_lock_date = fields.Date(
        help="Impossible to edit/create purchase journal entries prior to and "
        "inclusive of this date. Subject to exceptions.",
    )
    hard_lock_date = fields.Date(
        help="Impossible to edit/create journal entries prior to and "
        "inclusive of this date. This lock date is irreversible and "
        "does not allow any exception.",
    )

    # Read-only fields showing the effective floor enforced by ancestor companies.
    # Odoo 19 resolves lock dates as max(self, all ancestors), so a child company
    # date below these values has no additional effect.
    has_parent_company = fields.Boolean(compute="_compute_parent_lock_dates")
    parent_fiscalyear_lock_date = fields.Date(
        string="Parent Global Lock Date",
        compute="_compute_parent_lock_dates",
    )
    parent_tax_lock_date = fields.Date(
        string="Parent Tax Return Lock Date",
        compute="_compute_parent_lock_dates",
    )
    parent_sale_lock_date = fields.Date(compute="_compute_parent_lock_dates")
    parent_purchase_lock_date = fields.Date(compute="_compute_parent_lock_dates")
    parent_hard_lock_date = fields.Date(compute="_compute_parent_lock_dates")

    @api.depends("company_id")
    def _compute_parent_lock_dates(self):
        for wizard in self:
            company = wizard.company_id.sudo()
            # parent_ids includes self; subtract to get ancestors only
            ancestors = company.parent_ids - company
            wizard.has_parent_company = bool(ancestors)
            for lock_field in LOCK_DATE_FIELDS:
                dates = [c[lock_field] for c in ancestors if c[lock_field]]
                wizard[f"parent_{lock_field}"] = max(dates) if dates else False

    @api.model
    def default_get(self, field_list):
        res = super().default_get(field_list)
        company = self.env.company
        for lock_field in LOCK_DATE_FIELDS:
            res[lock_field] = company[lock_field]
        res["company_id"] = company.id
        return res

    def _check_execute_allowed(self):
        self.ensure_one()
        has_adviser_group = self.env.user.has_group("account.group_account_manager")
        if not (has_adviser_group or self.env.user._is_admin()):
            raise UserError(self.env._("You are not allowed to execute this action."))

    def _fix_redirect_warning(self, exc):
        """Rewrite account.bank.statement.line redirects to account.move.

        In Odoo 19, account.bank.statement.line has no standalone list/form
        views in core. When company._validate_locks() raises a RedirectWarning
        for unreconciled bank statement lines, we redirect to the parent
        account.move journal entries instead, which do have views.
        """
        action = exc.args[1] if len(exc.args) > 1 else {}
        if not (
            isinstance(action, dict)
            and action.get("res_model") == "account.bank.statement.line"
        ):
            return exc
        if action.get("res_id"):
            line = self.env["account.bank.statement.line"].browse(action["res_id"])
            new_action = dict(
                action,
                res_model="account.move",
                res_id=line.move_id.id,
                view_mode="form",
            )
        else:
            domain = action.get("domain", [])
            line_ids = next(
                (d[2] for d in domain if isinstance(d, (list, tuple)) and d[0] == "id"),
                [],
            )
            lines = self.env["account.bank.statement.line"].browse(line_ids)
            new_action = dict(
                action,
                res_model="account.move",
                view_mode="list,form",
                domain=[("id", "in", lines.move_id.ids)],
            )
            new_action.pop("res_id", None)
        return RedirectWarning(exc.args[0], new_action, *exc.args[2:])

    def execute(self):
        self.ensure_one()
        self._check_execute_allowed()
        today = fields.Date.context_today(self)
        fields_sr = (
            self.env["ir.model.fields"]
            .sudo()
            .search_read(
                [("model", "=", self._name), ("name", "in", LOCK_DATE_FIELDS)],
                ["field_description", "name"],
            )
        )
        field2string = dict(
            (field["name"], field["field_description"]) for field in fields_sr
        )
        vals = {}
        for lock_field in LOCK_DATE_FIELDS:
            if self[lock_field] and self[lock_field] > today:
                raise UserError(
                    self.env._(
                        "You tried to set %(field)s to %(date)s, "
                        "but it is in the future.",
                        field=field2string[lock_field],
                        date=format_date(self.env, self[lock_field]),
                    )
                )
            vals[lock_field] = self[lock_field]
        try:
            self.company_id.sudo().write(vals)
        except RedirectWarning as exc:
            raise self._fix_redirect_warning(exc) from exc
