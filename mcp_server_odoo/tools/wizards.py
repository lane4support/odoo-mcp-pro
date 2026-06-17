"""Drive Odoo wizards that business methods return, in three modes.

When a standard method (e.g. stock.picking.button_validate) returns an Odoo
wizard action instead of completing, we finish it with Odoo's OWN wizard:
create the transient model with the right context, then call its completion
method. None of Odoo's logic is reimplemented here.

The follow-up decision can come from (1) a caller-supplied parameter,
(2) MCP elicitation answered by a human or an agent, or (3) be deferred by
returning the available choices. This module owns the per-wizard schema and
apply logic; the three-mode orchestration lives in methods.py.

NOT validated against a live Odoo. The create+complete call sequence matches
the Odoo 19 source (stock/wizard/stock_backorder_confirmation.py,
account/wizard/account_payment_register.py) but real behaviour, especially how
each wizard populates its defaults from context, must be confirmed live.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from ..connection_protocol import OdooConnectionProtocol

# --- Per-wizard decision schemas (primitive fields only, per the MCP
#     elicitation spec: no nested objects or arrays of objects). ---


class BackorderDecision(BaseModel):
    """Follow-up for stock.backorder.confirmation."""

    create_backorder: bool = Field(
        description=(
            "Create a backorder for the unshipped quantity? Yes keeps the "
            "remaining items to deliver later; no cancels the backorder."
        ),
    )


class RegisterPaymentDecision(BaseModel):
    """Follow-up for account.payment.register. All optional: omit to take
    Odoo's computed defaults (full residual, today, default journal)."""

    journal_id: Optional[int] = Field(
        default=None, description="Payment journal id (e.g. Bank). Omit for Odoo's default."
    )
    amount: Optional[float] = Field(
        default=None, description="Amount to register. Omit to pay the full residual."
    )
    payment_date: Optional[str] = Field(
        default=None, description="Payment date as YYYY-MM-DD. Omit for today."
    )
    communication: Optional[str] = Field(
        default=None, description="Memo on the payment. Omit for Odoo's default."
    )


# --- Apply functions: create the wizard, call its completion method. ---


def _build_context(
    action: Dict[str, Any], origin_model: str, origin_ids: List[int]
) -> Dict[str, Any]:
    """Context for the wizard create.

    Starts from the action's OWN context and never overwrites it. Odoo sets the
    active_model / active_ids pairing itself: account.move.action_register_payment
    delegates to the move LINES, so its action carries
    active_model='account.move.line' with line ids -- overwriting active_ids with
    the move ids (our origin_ids) would make the wizard browse the wrong records.
    We only fill active_model / active_ids as a fallback for the rarer case where
    the action context omits them; then origin_model + origin_ids are consistent.
    """
    ctx = dict(action.get("context") or {})
    ctx.setdefault("active_model", origin_model)
    ctx.setdefault("active_ids", list(origin_ids or []))
    if origin_ids:
        ctx.setdefault("active_id", origin_ids[0])
    return ctx


def _apply_backorder(
    connection: OdooConnectionProtocol,
    action: Dict[str, Any],
    data: Dict[str, Any],
    origin_model: str,
    origin_ids: List[int],
) -> Dict[str, Any]:
    ctx = _build_context(action, origin_model, origin_ids)
    # button_validate puts default_pick_ids in the action context; derive it from
    # the originating pickings if it did not survive the RPC round-trip.
    if "default_pick_ids" not in ctx and origin_ids:
        ctx["default_pick_ids"] = [(4, pid) for pid in origin_ids]
    # process()/process_cancel_backorder() act on context['button_validate_picking_ids'];
    # without it the wizard returns True and validates NOTHING. Odoo sets this key
    # when it opens the wizard; ensure it from the originating pickings as a guard
    # so we cannot silently no-op.
    if "button_validate_picking_ids" not in ctx and origin_ids:
        ctx["button_validate_picking_ids"] = list(origin_ids)
    wiz_id = connection.create("stock.backorder.confirmation", {}, context=ctx)
    method = "process" if data.get("create_backorder") else "process_cancel_backorder"
    result = connection.call_method("stock.backorder.confirmation", method, ids=[wiz_id])
    verb = "with a backorder" if data.get("create_backorder") else "without a backorder"
    return {"completion_method": method, "result": result, "message": f"Validated {verb}."}


def _apply_register_payment(
    connection: OdooConnectionProtocol,
    action: Dict[str, Any],
    data: Dict[str, Any],
    origin_model: str,
    origin_ids: List[int],
) -> Dict[str, Any]:
    ctx = _build_context(action, origin_model, origin_ids)
    vals = {k: v for k, v in data.items() if v is not None}
    wiz_id = connection.create("account.payment.register", vals, context=ctx)
    result = connection.call_method(
        "account.payment.register", "action_create_payments", ids=[wiz_id]
    )
    return {
        "completion_method": "action_create_payments",
        "result": result,
        "message": "Payment registered.",
    }


class WizardHandler:
    """Knows how to ask the follow-up and how to complete one wizard."""

    def __init__(
        self,
        res_model: str,
        schema: type[BaseModel],
        apply: Callable[..., Dict[str, Any]],
        prompt: str,
    ):
        self.res_model = res_model
        self.schema = schema
        self.apply = apply
        self.prompt = prompt


WIZARD_REGISTRY: Dict[str, WizardHandler] = {
    "stock.backorder.confirmation": WizardHandler(
        "stock.backorder.confirmation",
        BackorderDecision,
        _apply_backorder,
        "This delivery is not fully done. Create a backorder for the remaining quantity?",
    ),
    "account.payment.register": WizardHandler(
        "account.payment.register",
        RegisterPaymentDecision,
        _apply_register_payment,
        "Register a payment for this record? Set journal, amount and date, or accept the defaults.",
    ),
}


def get_handler(action: Optional[Dict[str, Any]]) -> Optional[WizardHandler]:
    """Return the handler for a returned action dict, or None if unknown."""
    if not isinstance(action, dict):
        return None
    return WIZARD_REGISTRY.get(action.get("res_model"))


def followup_descriptor(handler: WizardHandler) -> Dict[str, Any]:
    """Describe a wizard's decision fields for the deferred (mode 3) response."""
    schema = handler.schema.model_json_schema()
    return {
        "wizard": handler.res_model,
        "decision_fields": schema.get("properties", {}),
        "hint": (
            "Re-call execute_method with decision={...} to complete this wizard, "
            "or use a client that supports MCP elicitation."
        ),
    }
