"""Tests for the generic execute_method tool."""

from unittest.mock import Mock

import pytest

from mcp_server_odoo.access_control import AccessControlError
from mcp_server_odoo.error_handling import ValidationError
from mcp_server_odoo.tools import OdooToolHandler
from mcp_server_odoo.tools.methods import _classify_result


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"type": "ir.actions.act_window", "res_model": "x"}, "action"),
        ({"type": "ir.actions.client", "tag": "reload"}, "action"),
        ({"res_model": "account.move", "view_mode": "form"}, "action"),
        ({"res_model": "sale.order", "count": 3}, "value"),  # plain dict, not an action
        ({"type": 5, "res_model": "x"}, "value"),  # non-str type must not crash
        ({"state": "posted"}, "value"),
        ([1, 2, 3], "records"),
        ([], "value"),
        (["a", "b"], "value"),
        ([1, "a"], "value"),
        (True, "value"),
        (None, "value"),
        ("ok", "value"),
        (42, "value"),
    ],
)
def test_classify_result(value, expected):
    assert _classify_result(value) == expected


class TestExecuteMethod:
    """Test the execute_method tool handler."""

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
    def mock_config(self):
        config = Mock()
        config.url = "http://localhost:8069"
        return config

    @pytest.fixture
    def handler(self, mock_app, mock_connection, mock_access_controller, mock_config):
        return OdooToolHandler(mock_app, mock_connection, mock_access_controller, mock_config)

    @pytest.mark.asyncio
    async def test_value_return_passes_through(self, handler, mock_connection):
        """A real method that returns True is reported as a plain value."""
        mock_connection.call_method.return_value = True

        result = await handler._handle_execute_method_tool("sale.order", "action_confirm", ids=[42])

        assert result["success"] is True
        assert result["result_kind"] == "value"
        assert result["result"] is True
        assert result["action"] is None
        # Called Odoo's own method unchanged, no reimplementation.
        mock_connection.call_method.assert_called_once_with(
            "sale.order", "action_confirm", ids=[42]
        )

    @pytest.mark.asyncio
    async def test_record_ids_return(self, handler, mock_connection):
        """A list of ids is classified as records."""
        mock_connection.call_method.return_value = [7, 8]

        result = await handler._handle_execute_method_tool("crm.lead", "action_set_won", ids=[7, 8])

        assert result["result_kind"] == "records"
        assert result["result"] == [7, 8]

    @pytest.mark.asyncio
    async def test_unknown_action_dict_is_surfaced(self, handler, mock_connection):
        """An action for a wizard we do not auto-handle is surfaced as 'action'."""
        wizard = {
            "type": "ir.actions.act_window",
            "res_model": "some.custom.wizard",
            "target": "new",
        }
        mock_connection.call_method.return_value = wizard

        result = await handler._handle_execute_method_tool("x.model", "do_something", ids=[5])

        assert result["result_kind"] == "action"
        assert result["action"] == wizard
        assert result["followup"] is None
        assert "not auto-handled" in result["message"]

    @pytest.mark.asyncio
    async def test_private_method_rejected(self, handler, mock_connection):
        """Private (underscore) methods are refused, mirroring Odoo's API."""
        with pytest.raises(ValidationError, match="private method"):
            await handler._handle_execute_method_tool("sale.order", "_create_invoices", ids=[1])
        mock_connection.call_method.assert_not_called()

    @pytest.mark.asyncio
    async def test_kwargs_forwarded(self, handler, mock_connection):
        """kwargs reach the Odoo method unchanged."""
        mock_connection.call_method.return_value = True

        await handler._handle_execute_method_tool(
            "crm.lead", "action_set_lost", ids=[3], kwargs={"lost_reason_id": 2}
        )

        mock_connection.call_method.assert_called_once_with(
            "crm.lead", "action_set_lost", ids=[3], lost_reason_id=2
        )

    @pytest.mark.asyncio
    async def test_access_denied_becomes_validation_error(self, handler, mock_access_controller):
        """Odoo-side access denial surfaces as a clean error."""
        mock_access_controller.validate_model_access.side_effect = AccessControlError("nope")

        with pytest.raises(ValidationError, match="Access denied"):
            await handler._handle_execute_method_tool("account.move", "action_post", ids=[1])
