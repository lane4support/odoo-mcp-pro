"""Tests for the wizard follow-up layer (three modes) on execute_method.

Mock-based: they assert the create + completion call SEQUENCE matches the
Odoo 19 wizard API. They do NOT prove real Odoo behaviour (no live instance).
"""

from unittest.mock import Mock

import anyio
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from mcp_server_odoo.error_handling import ValidationError
from mcp_server_odoo.tools import OdooToolHandler
from mcp_server_odoo.tools.wizards import BackorderDecision


class FakeElicit:
    """Stand-in for an MCP client answering (or refusing) an elicitation."""

    def __init__(self, action, data=None):
        self._action = action
        self._data = data

    async def elicit(self, message, schema):
        return Mock(action=self._action, data=self._data)


BACKORDER_ACTION = {
    "type": "ir.actions.act_window",
    "res_model": "stock.backorder.confirmation",
    "context": {"default_pick_ids": [(4, 5)], "default_show_transfers": False},
}

PAYMENT_ACTION = {
    "type": "ir.actions.act_window",
    "res_model": "account.payment.register",
    "context": {},
}


class TestWizardFollowup:
    @pytest.fixture
    def mock_app(self):
        app = Mock()
        app.tool = Mock(side_effect=lambda **kwargs: lambda func: func)
        return app

    @pytest.fixture
    def mock_connection(self):
        conn = Mock()
        conn.is_authenticated = True
        conn._base_url = "http://localhost:8069"
        return conn

    @pytest.fixture
    def mock_access_controller(self):
        controller = Mock()
        controller.validate_model_access = Mock()
        return controller

    @pytest.fixture
    def handler(self, mock_app, mock_connection, mock_access_controller):
        config = Mock()
        config.url = "http://localhost:8069"
        return OdooToolHandler(mock_app, mock_connection, mock_access_controller, config)

    # --- Mode 1: decision supplied up front (n8n / agent path) ---

    @pytest.mark.asyncio
    async def test_backorder_decision_yes_creates_backorder(self, handler, mock_connection):
        mock_connection.call_method.side_effect = [BACKORDER_ACTION, True]
        mock_connection.create.return_value = 99

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], decision={"create_backorder": True}
        )

        assert result["result_kind"] == "completed"
        # Wizard created with the action context (carries default_pick_ids).
        model_arg, vals_arg = mock_connection.create.call_args.args
        assert model_arg == "stock.backorder.confirmation"
        assert vals_arg == {}
        assert "default_pick_ids" in mock_connection.create.call_args.kwargs["context"]
        # Completion method is process() for "yes".
        second = mock_connection.call_method.call_args_list[1]
        assert second.args[:2] == ("stock.backorder.confirmation", "process")
        assert second.kwargs["ids"] == [99]

    @pytest.mark.asyncio
    async def test_backorder_decision_no_cancels_backorder(self, handler, mock_connection):
        mock_connection.call_method.side_effect = [BACKORDER_ACTION, True]
        mock_connection.create.return_value = 99

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], decision={"create_backorder": False}
        )

        assert result["result_kind"] == "completed"
        second = mock_connection.call_method.call_args_list[1]
        assert second.args[:2] == ("stock.backorder.confirmation", "process_cancel_backorder")

    @pytest.mark.asyncio
    async def test_register_payment_decision_passes_vals_and_context(
        self, handler, mock_connection
    ):
        mock_connection.call_method.side_effect = [PAYMENT_ACTION, {"payment": 1}]
        mock_connection.create.return_value = 77

        result = await handler._handle_execute_method_tool(
            "account.move",
            "action_register_payment",
            ids=[10],
            decision={"journal_id": 7, "amount": 100.0, "payment_date": "2026-06-18"},
        )

        assert result["result_kind"] == "completed"
        model_arg, vals_arg = mock_connection.create.call_args.args
        assert model_arg == "account.payment.register"
        # Only non-null fields are passed as vals.
        assert vals_arg == {"journal_id": 7, "amount": 100.0, "payment_date": "2026-06-18"}
        # active_model/active_ids pinned from the originating invoice.
        ctx = mock_connection.create.call_args.kwargs["context"]
        assert ctx["active_model"] == "account.move"
        assert ctx["active_ids"] == [10]
        second = mock_connection.call_method.call_args_list[1]
        assert second.args[:2] == ("account.payment.register", "action_create_payments")

    @pytest.mark.asyncio
    async def test_invalid_decision_raises(self, handler, mock_connection):
        mock_connection.call_method.side_effect = [BACKORDER_ACTION]

        with pytest.raises(ValidationError, match="Invalid decision"):
            await handler._handle_execute_method_tool(
                "stock.picking", "button_validate", ids=[5], decision={"wrong_field": 1}
            )

    # --- Mode 2: elicitation (human or agent answers) ---

    @pytest.mark.asyncio
    async def test_backorder_elicit_accept(self, handler, mock_connection):
        mock_connection.call_method.side_effect = [BACKORDER_ACTION, True]
        mock_connection.create.return_value = 99
        ctx = FakeElicit("accept", data=BackorderDecision(create_backorder=True))

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], ctx=ctx
        )

        assert result["result_kind"] == "completed"
        second = mock_connection.call_method.call_args_list[1]
        assert second.args[:2] == ("stock.backorder.confirmation", "process")

    @pytest.mark.asyncio
    async def test_backorder_elicit_decline_defers(self, handler, mock_connection):
        mock_connection.call_method.side_effect = [BACKORDER_ACTION]
        ctx = FakeElicit("decline")

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], ctx=ctx
        )

        assert result["result_kind"] == "action"
        assert result["followup"]["wizard"] == "stock.backorder.confirmation"
        # No wizard was created when the user declined.
        mock_connection.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_elicit_unsupported_defers(self, handler, mock_connection):
        """A client without elicitation capability raises McpError -> defer."""
        mock_connection.call_method.side_effect = [BACKORDER_ACTION]

        class Boom:
            async def elicit(self, message, schema):
                raise McpError(ErrorData(code=-32601, message="elicitation not supported"))

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], ctx=Boom()
        )

        assert result["result_kind"] == "action"
        assert result["followup"]["wizard"] == "stock.backorder.confirmation"
        mock_connection.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_elicit_transport_closed_defers(self, handler, mock_connection):
        """A gone transport (anyio stream error) is a 'cannot ask' -> defer."""
        mock_connection.call_method.side_effect = [BACKORDER_ACTION]

        class Boom:
            async def elicit(self, message, schema):
                raise anyio.ClosedResourceError()

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], ctx=Boom()
        )

        assert result["result_kind"] == "action"
        mock_connection.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_elicit_unexpected_error_propagates(self, handler, mock_connection):
        """A non-McpError, non-transport error during elicit is a real bug."""
        mock_connection.call_method.side_effect = [BACKORDER_ACTION]

        class Boom:
            async def elicit(self, message, schema):
                raise RuntimeError("genuine bug")

        with pytest.raises(ValidationError, match="Failed to execute"):
            await handler._handle_execute_method_tool(
                "stock.picking", "button_validate", ids=[5], ctx=Boom()
            )

    # --- Mode 3: no decision, no client -> defer with the choices ---

    @pytest.mark.asyncio
    async def test_no_decision_no_ctx_defers_with_fields(self, handler, mock_connection):
        mock_connection.call_method.side_effect = [BACKORDER_ACTION]

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5]
        )

        assert result["result_kind"] == "action"
        assert "create_backorder" in result["followup"]["decision_fields"]
        assert result["result"] is None  # action lives in `action`, not duplicated
        mock_connection.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_decision_defers_not_errors(self, handler, mock_connection):
        """decision={} means 'no decision yet', not an invalid payload."""
        mock_connection.call_method.side_effect = [BACKORDER_ACTION]

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], decision={}
        )

        assert result["result_kind"] == "action"
        mock_connection.create.assert_not_called()

    # --- Register payment specifics ---

    @pytest.mark.asyncio
    async def test_register_payment_elicit_accept_strips_none_vals(self, handler, mock_connection):
        from mcp_server_odoo.tools.wizards import RegisterPaymentDecision

        mock_connection.call_method.side_effect = [PAYMENT_ACTION, {"payment": 1}]
        mock_connection.create.return_value = 77
        ctx = FakeElicit("accept", data=RegisterPaymentDecision(journal_id=7))

        result = await handler._handle_execute_method_tool(
            "account.move", "action_register_payment", ids=[10], ctx=ctx
        )

        assert result["result_kind"] == "completed"
        # Only the set field reaches vals; None fields are dropped.
        _, vals_arg = mock_connection.create.call_args.args
        assert vals_arg == {"journal_id": 7}

    @pytest.mark.asyncio
    async def test_register_payment_preserves_action_active_ids(self, handler, mock_connection):
        """Bug guard: do not clobber active_model/active_ids the action set."""
        action = {
            "type": "ir.actions.act_window",
            "res_model": "account.payment.register",
            "context": {"active_model": "account.move.line", "active_ids": [101, 102]},
        }
        mock_connection.call_method.side_effect = [action, {"payment": 1}]
        mock_connection.create.return_value = 77

        await handler._handle_execute_method_tool(
            "account.move", "action_register_payment", ids=[10], decision={"amount": 50.0}
        )

        ctx = mock_connection.create.call_args.kwargs["context"]
        # The line-ids context Odoo set must survive, NOT be overwritten by [10].
        assert ctx["active_model"] == "account.move.line"
        assert ctx["active_ids"] == [101, 102]

    @pytest.mark.asyncio
    async def test_decision_ignores_unknown_keys(self, handler, mock_connection):
        """Extra keys in decision are ignored (pydantic extra=ignore default)."""
        mock_connection.call_method.side_effect = [BACKORDER_ACTION, True]
        mock_connection.create.return_value = 99

        result = await handler._handle_execute_method_tool(
            "stock.picking",
            "button_validate",
            ids=[5],
            decision={"create_backorder": True, "bogus": 9},
        )

        assert result["result_kind"] == "completed"
        _, vals_arg = mock_connection.create.call_args.args
        assert "bogus" not in vals_arg

    @pytest.mark.asyncio
    async def test_followup_descriptor_payment_fields(self, handler, mock_connection):
        mock_connection.call_method.side_effect = [PAYMENT_ACTION]

        result = await handler._handle_execute_method_tool(
            "account.move", "action_register_payment", ids=[10]
        )

        fields = result["followup"]["decision_fields"]
        assert set(fields) == {"journal_id", "amount", "payment_date", "communication"}
        assert result["followup"]["wizard"] == "account.payment.register"

    @pytest.mark.asyncio
    async def test_completed_passes_completion_result_through(self, handler, mock_connection):
        """The completion call's return value is surfaced in `result`."""
        payment = {"some": "payment-summary"}  # not an action (no type/view keys)
        mock_connection.call_method.side_effect = [PAYMENT_ACTION, payment]
        mock_connection.create.return_value = 77

        result = await handler._handle_execute_method_tool(
            "account.move", "action_register_payment", ids=[10], decision={"amount": 5.0}
        )

        assert result["result_kind"] == "completed"
        assert result["result"] == payment

    @pytest.mark.asyncio
    async def test_chained_wizard_not_marked_completed(self, handler, mock_connection):
        """If the completion returns another action, do not claim 'completed'."""
        chained = {
            "type": "ir.actions.act_window",
            "res_model": "account.payment.register",
            "target": "new",
        }
        mock_connection.call_method.side_effect = [BACKORDER_ACTION, chained]
        mock_connection.create.return_value = 99

        result = await handler._handle_execute_method_tool(
            "stock.picking", "button_validate", ids=[5], decision={"create_backorder": True}
        )

        assert result["result_kind"] == "action"
        assert result["action"] == chained
