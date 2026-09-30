# Copyright 2009-2018 Noviat
# Copyright 2021 Tecnativa - João Marques
# Copyright 2021 Tecnativa - Víctor Martínez
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

# List of move's fields that can't be modified if move is linked
# with a depreciation line
FIELDS_AFFECTS_ASSET_MOVE = {"journal_id", "date"}
# List of move line's fields that can't be modified if move is linked
# with a depreciation line
FIELDS_AFFECTS_ASSET_MOVE_LINE = {
    "credit",
    "debit",
    "account_id",
    "journal_id",
    "date",
    "asset_profile_id",
    "asset_id",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    asset_count = fields.Integer(compute="_compute_asset_count")

    def _compute_asset_count(self):
        rg_res = self.env["account.asset.line"]._read_group(
            [("move_id", "in", self.ids)], groupby=["move_id"], aggregates=["__count"]
        )
        mapped_data = {move.id: count for move, count in rg_res}
        for move in self:
            move.asset_count = mapped_data.get(move.id, 0)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_linked_to_asset(self):
        # for move in self:
        deprs = (
            self.env["account.asset.line"]
            .sudo()
            .search(
                [("move_id", "in", self.ids), ("type", "in", ["depreciate", "remove"])]
            )
        )
        if deprs and not self.env.context.get("unlink_from_asset"):
            raise UserError(
                self.env._(
                    "You are not allowed to remove an accounting entry "
                    "linked to an asset."
                    "\nYou should remove such entries from the asset."
                )
            )

    def unlink(self):
        deprs = (
            self.env["account.asset.line"]
            .sudo()
            .search(
                [("move_id", "in", self.ids), ("type", "in", ["depreciate", "remove"])]
            )
        )
        # trigger store function
        deprs.write({"move_id": False})
        return super().unlink()

    def write(self, vals):
        if set(vals).intersection(FIELDS_AFFECTS_ASSET_MOVE):
            deprs = (
                self.env["account.asset.line"]
                .sudo()
                .search([("move_id", "in", self.ids), ("type", "=", "depreciate")])
            )
            if deprs:
                raise UserError(
                    self.env._(
                        "You cannot change an accounting entry "
                        "linked to an asset depreciation line."
                    )
                )
        return super().write(vals)

    def _prepare_asset_vals(self, aml):
        depreciation_base = aml.balance
        return {
            "name": aml.name,
            "code": self.name,
            "profile_id": aml.asset_profile_id.id,
            "purchase_value": depreciation_base,
            "partner_id": aml.partner_id.id,
            "date_start": self.date,
        }

    def action_post(self):
        ret_val = super().action_post()
        for move in self:
            for aml in move.line_ids.filtered(
                lambda line: line.asset_profile_id and not line.tax_line_id
            ):
                if not aml.name:
                    raise UserError(
                        self.env._("Asset name must be set in the label of the line.")
                    )
                if aml.asset_id:
                    continue
                vals = move._prepare_asset_vals(aml)
                asset = (
                    self.env["account.asset"]
                    .with_company(move.company_id)
                    .with_context(create_asset_from_move_line=True, move_id=move.id)
                    .create(vals)
                )
                asset.analytic_distribution = aml.analytic_distribution
                aml.with_context(
                    allow_asset=True, allow_asset_removal=True
                ).asset_id = asset.id
            new_name_get = []
            for asset in move.line_ids.filtered("asset_profile_id").asset_id:
                new_name_get = [asset.id, asset.display_name]
            if new_name_get:
                message = self.env._(
                    "This invoice created the asset(s): %s",
                    Markup(
                        """<a href=# data-oe-model=account.asset"""
                        f""" data-oe-id={new_name_get[0]}"""
                        f""">{new_name_get[1]}</a>"""
                    ),
                )
                move.message_post(body=message)
        return ret_val

    def button_draft(self):
        invoices = self.filtered(lambda r: r.is_purchase_document())
        if invoices:
            invoices.line_ids.asset_id.unlink()
        return super().button_draft()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        # 20.0 deleted _reverse_move_vals, the hook the 19.0 code extended:
        # reverses are built with copy() now, so there is no vals dict to edit
        # and the work has to happen around the created records.
        #
        # Two field flags shape what is needed. asset_id is copy=False, so a
        # reverse line never carries it -- nothing to clear there. But
        # asset_profile_id IS copied, so an uncleared reverse would create a
        # fresh asset on post, which is the opposite of reversing. And
        # account.asset.unlink() already clears asset_id on every referencing
        # move line, so the ondelete="restrict" needs no handling here.
        assets_to_remove = self.env["account.asset"]
        reverse_source = {}
        for move in self:
            if move.move_type in ("out_invoice", "out_refund"):
                continue
            for line in move.line_ids.filtered("asset_id"):
                # Only remove the asset when this really is the reversal of the
                # move that created it, not of some later depreciation entry.
                asset_line = self.env["account.asset.line"].search(
                    [("asset_id", "=", line.asset_id.id), ("type", "=", "create")],
                    limit=1,
                )
                if asset_line and asset_line.move_id == move:
                    assets_to_remove |= line.asset_id
                    reverse_source[move.id] = True

        reverse_moves = super()._reverse_moves(default_values_list, cancel)

        if assets_to_remove:
            assets_to_remove.unlink()
            # Clear the copied profile on every line of the affected reverses:
            # undoing an asset creation must not hand the reversal what it
            # needs to create another one.
            for move, reverse_move in zip(self, reverse_moves, strict=False):
                if reverse_source.get(move.id):
                    reverse_move.line_ids.filtered("asset_profile_id").write(
                        {"asset_profile_id": False}
                    )
        return reverse_moves

    def action_view_assets(self):
        assets = (
            self.env["account.asset.line"]
            .search([("move_id", "=", self.id)])
            .mapped("asset_id")
        )
        action = self.env.ref("account_asset_management.account_asset_action")
        action_dict = action.sudo().read()[0]
        if len(assets) == 1:
            res = self.env.ref(
                "account_asset_management.account_asset_view_form", False
            )
            action_dict["views"] = [(res and res.id or False, "form")]
            action_dict["res_id"] = assets.id
        elif assets:
            action_dict["domain"] = [("id", "in", assets.ids)]
        else:
            action_dict = {"type": "ir.actions.act_window_close"}
        return action_dict


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    asset_profile_id = fields.Many2one(
        comodel_name="account.asset.profile",
        compute="_compute_asset_profile",
        store=True,
        readonly=False,
    )
    asset_id = fields.Many2one(
        comodel_name="account.asset",
        ondelete="restrict",
        check_company=True,
        copy=False,
    )

    @api.depends("account_id", "asset_id")
    def _compute_asset_profile(self):
        for rec in self:
            if rec.account_id.asset_profile_id and not rec.asset_id:
                rec.asset_profile_id = rec.account_id.asset_profile_id
            elif rec.asset_id:
                rec.asset_profile_id = rec.asset_id.profile_id

    @api.onchange("asset_profile_id")
    def _onchange_asset_profile_id(self):
        if (
            self.asset_profile_id.account_asset_id
            and self.asset_profile_id.account_asset_id != self.account_id
        ):
            self.account_id = self.asset_profile_id.account_asset_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            move = self.env["account.move"].browse(vals.get("move_id"))
            if not move.is_sale_document():
                if vals.get("asset_id") and not self.env.context.get("allow_asset"):
                    raise UserError(
                        self.env._(
                            "You are not allowed to link "
                            "an accounting entry to an asset."
                            "\nYou should generate such entries from the asset."
                        )
                    )
        records = super().create(vals_list)
        for record in records:
            record._expand_asset_line()
        return records

    def write(self, vals):
        if set(vals).intersection(FIELDS_AFFECTS_ASSET_MOVE_LINE) and not (
            self.env.context.get("allow_asset_removal")
            and list(vals.keys()) == ["asset_id"]
        ):
            # Check if at least one asset is linked to a move
            linked_asset = False
            for move_line in self.filtered(lambda r: not r.move_id.is_sale_document()):
                linked_asset = move_line.asset_id
                if linked_asset:
                    raise UserError(
                        self.env._(
                            "You cannot change an accounting item "
                            "linked to an asset depreciation line."
                        )
                    )

        if (
            self.filtered(lambda r: not r.move_id.is_sale_document())
            and vals.get("asset_id")
            and not self.env.context.get("allow_asset")
        ):
            raise UserError(
                self.env._(
                    "You are not allowed to link "
                    "an accounting entry to an asset."
                    "\nYou should generate such entries from the asset."
                )
            )
        super().write(vals)
        if "quantity" in vals or "asset_profile_id" in vals:
            for record in self:
                record._expand_asset_line()
        return True

    def _expand_asset_line(self):
        self.ensure_one()
        if self.asset_profile_id.asset_product_item and self.quantity > 1.0:
            aml = self.with_context(check_move_validity=False)
            qty = self.quantity
            name = self.name
            aml.write({"quantity": 1, "name": f"{name} {1}"})
            for i in range(1, int(qty)):
                aml.copy({"name": f"{name} {i + 1}"})
