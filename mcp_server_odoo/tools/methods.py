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

from mcp.types import ToolAnnotations

from ..access_control import AccessControlError
from ..error_handling import ValidationError
from ..error_sanitizer import ErrorSanitizer
from ..logging_config import perf_logger
from ..odoo_connection import OdooConnectionError
from ..schemas import ExecuteMethodResult
from ._common import _current_sub, logger


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
        ) -> ExecuteMethodResult:
            """Call a public method on an Odoo model or recordset.

            This is the standard Odoo way to trigger an action that is not plain
            create/read/update/delete: confirming a sales order, posting an
            invoice, marking a CRM lead lost, validating a delivery, and so on.
            It runs Odoo's own method unchanged.

            Args:
                model: Odoo model name, e.g. 'sale.order', 'account.move'.
                method: Public method to call, e.g. 'action_confirm',
                    'action_post', 'action_set_lost'. Private methods (names
                    starting with '_') are rejected, exactly as Odoo's API does.
                ids: Record ids to call the method on (the recordset). Omit for
                    a model-level (`@api.model`) method.
                kwargs: Keyword arguments for the method, if it takes any.

            Returns:
                The raw return value, classified as a plain value, a list of
                record ids, or an Odoo action dict (a wizard or window action
                that the UI would normally open next).
            """
            result = await self._handle_execute_method_tool(model, method, ids, kwargs)
            self._track_usage(_current_sub.get(), "execute_method")
            return ExecuteMethodResult(**result)

    async def _handle_execute_method_tool(
        self,
        model: str,
        method: str,
        ids: Optional[List[int]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
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
                action = value if kind == "action" else None

                if kind == "action":
                    summary = (
                        f"{model}.{method} returned an Odoo action "
                        f"({value.get('res_model') or value.get('type')}); "
                        "a follow-up step would be needed to complete it."
                    )
                elif kind == "records":
                    summary = f"{model}.{method} returned {len(value)} record id(s)."
                else:
                    summary = f"{model}.{method} completed."

                return {
                    "success": True,
                    "model": model,
                    "method": method,
                    "result_kind": kind,
                    "result": value,
                    "action": action,
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
