"""Generic ORM method tool: execute_method.

Calls a public Odoo method on a model or recordset, the same way Odoo's own
external API (`execute_kw`) does. Nothing is reimplemented; we pass the call
straight through to the live Odoo via the transport-agnostic `call_method`.

Odoo's own access rights are the only gate: the connected user must be allowed
to run the method, and Odoo's RPC layer already refuses private (leading
underscore) methods. We mirror that one rule with a clear error and otherwise
stay out of the way.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..access_control import AccessControlError
from ..error_handling import ValidationError
from ..error_sanitizer import ErrorSanitizer
from ..logging_config import perf_logger
from ..odoo_connection import OdooConnectionError
from ..schemas import ExecuteMethodResult
from ._common import _current_sub, logger
from .wizards import WizardHandler, followup_descriptor, get_handler


def _classify_result(value: Any) -> str:
    """Bucket a method return into value / records / action.

    - dict that looks like an Odoo action (window/client action or a wizard,
      i.e. carries a `res_model` or an `ir.actions.*` type) -> 'action'
    - list of ints (record ids) -> 'records'
    - anything else (bool, number, string, None, plain dict) -> 'value'
    """
    if isinstance(value, dict):
        is_action = value.get("type", "").startswith("ir.actions.") or "res_model" in value
        if is_action:
            return "action"
        return "value"
    if isinstance(value, list) and value and all(isinstance(v, int) for v in value):
        return "records"
    return "value"


class MethodsToolsMixin:
    """execute_method tool."""

    def _register_methods_tools(self):
        """Register the execute_method tool with FastMCP."""

        @self.app.tool(
            title="Execute Odoo Method (call a standard Odoo action)",
            annotations=ToolAnnotations(
                # A method can do anything from read-only to destructive; we cannot
                # know in advance, so we flag the cautious defaults.
                readOnlyHint=False,
                destructiveHint=True,
                idempotentHint=False,
                openWorldHint=True,
            ),
        )
        async def execute_method(
            model: str,
            method: str,
            ids: Optional[List[int]] = None,
            kwargs: Optional[Dict[str, Any]] = None,
            decision: Optional[Dict[str, Any]] = None,
            ctx: Context = None,
        ) -> ExecuteMethodResult:
            """Call a public method on an Odoo model or recordset.

            This is the standard Odoo way to trigger an action that is not plain
            create/read/update/delete: confirming a sales order, posting an
            invoice, marking a CRM lead lost, validating a delivery, and so on.
            It runs Odoo's own method unchanged.

            Some methods return a wizard instead of completing (e.g. validating a
            delivery that is short on stock asks whether to create a backorder).
            For known wizards this tool finishes them with Odoo's own wizard:
            pass the answer up front via `decision`, or let your client ask you
            (MCP elicitation). If neither is possible, the wizard's options are
            returned so you can re-call with `decision`.

            Args:
                model: Odoo model name, e.g. 'sale.order', 'account.move'.
                method: Public method to call, e.g. 'action_confirm',
                    'action_post', 'action_set_lost'. Private methods (names
                    starting with '_') are rejected, exactly as Odoo's API does.
                ids: Record ids to call the method on (the recordset). Omit for
                    a model-level (`@api.model`) method.
                kwargs: Keyword arguments for the method, if it takes any.
                decision: Pre-answer for a follow-up wizard, e.g.
                    {"create_backorder": true} or {"journal_id": 7}. Lets a flow
                    or agent complete the wizard without being asked.

            Returns:
                The raw return value, classified as a plain value, record ids, an
                Odoo action (wizard still needing a decision), or 'completed' when
                a known wizard was driven to the end for you.
            """
            result = await self._handle_execute_method_tool(
                model, method, ids, kwargs, decision=decision, ctx=ctx
            )
            self._track_usage(_current_sub.get(), "execute_method")
            return ExecuteMethodResult(**result)

    async def _handle_execute_method_tool(
        self,
        model: str,
        method: str,
        ids: Optional[List[int]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        decision: Optional[Dict[str, Any]] = None,
        ctx: Optional[Context] = None,
    ) -> Dict[str, Any]:
        """Handle execute_method tool request."""
        try:
            connection, access_controller, sub = await self._get_user_context()
            with perf_logger.track_operation("tool_execute_method", model=model):
                if not method or not method.strip():
                    raise ValidationError("method is required")
                # Mirror Odoo's own public/private boundary: the RPC layer refuses
                # underscore methods, so reject them up front with a clear message.
                if method.startswith("_"):
                    raise ValidationError(
                        f"Cannot call private method '{method}'. Only public Odoo "
                        "methods are callable, the same as Odoo's external API."
                    )

                # Touching a model at all needs read access; everything beyond that
                # is enforced by Odoo when the method runs.
                access_controller.validate_model_access(model, "read")

                if not connection.is_authenticated:
                    raise ValidationError("Not authenticated with Odoo")

                value = connection.call_method(model, method, ids=ids, **(kwargs or {}))

                kind = _classify_result(value)

                if kind == "action":
                    handler = get_handler(value)
                    if handler is not None:
                        return await self._drive_wizard(
                            connection, handler, value, decision, ctx, model, method, ids or []
                        )
                    return {
                        "success": True,
                        "model": model,
                        "method": method,
                        "result_kind": "action",
                        "result": value,
                        "action": value,
                        "followup": None,
                        "message": (
                            f"{model}.{method} returned an Odoo action "
                            f"({value.get('res_model') or value.get('type')}); "
                            "this wizard is not auto-handled, complete it in Odoo."
                        ),
                    }

                if kind == "records":
                    summary = f"{model}.{method} returned {len(value)} record id(s)."
                else:
                    summary = f"{model}.{method} completed."

                return {
                    "success": True,
                    "model": model,
                    "method": method,
                    "result_kind": kind,
                    "result": value,
                    "action": None,
                    "followup": None,
                    "message": summary,
                }

        except ValidationError:
            raise
        except AccessControlError as e:
            raise ValidationError(f"Access denied: {e}") from e
        except OdooConnectionError as e:
            raise ValidationError(f"Connection error: {e}") from e
        except Exception as e:
            logger.error(f"Error in execute_method tool: {e}")
            sanitized_msg = ErrorSanitizer.sanitize_message(str(e))
            raise ValidationError(f"Failed to execute {model}.{method}: {sanitized_msg}") from e

    async def _drive_wizard(
        self,
        connection,
        handler: WizardHandler,
        action: Dict[str, Any],
        decision: Optional[Dict[str, Any]],
        ctx: Optional[Context],
        model: str,
        method: str,
        ids: List[int],
    ) -> Dict[str, Any]:
        """Three-mode follow-up for a known wizard.

        1. `decision` supplied -> apply it (no human / no client needed).
        2. else if the client can be asked -> MCP elicitation.
        3. else -> return the wizard's decision fields so the caller can re-call.
        """
        data: Optional[Dict[str, Any]] = None

        if decision is not None:
            try:
                data = handler.schema(**decision).model_dump()
            except Exception as e:
                raise ValidationError(f"Invalid decision for {handler.res_model}: {e}") from e
        elif ctx is not None:
            data = await self._try_elicit(ctx, handler)

        if data is not None:
            completion = handler.apply(connection, action, data, model, ids)
            return {
                "success": True,
                "model": model,
                "method": method,
                "result_kind": "completed",
                "result": completion.get("result"),
                "action": action,
                "followup": None,
                "message": (
                    f"{model}.{method} -> {completion.get('message')} "
                    f"(via {handler.res_model}.{completion.get('completion_method')})"
                ),
            }

        # Mode 3: defer with the decision fields.
        return {
            "success": True,
            "model": model,
            "method": method,
            "result_kind": "action",
            "result": action,
            "action": action,
            "followup": followup_descriptor(handler),
            "message": (
                f"{model}.{method} needs a decision: {handler.prompt} "
                "Re-call with decision={...}."
            ),
        }

    async def _try_elicit(self, ctx: Context, handler: WizardHandler) -> Optional[Dict[str, Any]]:
        """Ask the client for the wizard decision. None if unavailable/declined."""
        try:
            result = await ctx.elicit(message=handler.prompt, schema=handler.schema)
        except Exception as e:
            # Client does not support elicitation, or the round-trip failed.
            logger.info("elicitation unavailable for %s: %s", handler.res_model, e)
            return None
        if getattr(result, "action", None) == "accept" and getattr(result, "data", None):
            data = result.data
            return data.model_dump() if hasattr(data, "model_dump") else dict(data)
        return None
