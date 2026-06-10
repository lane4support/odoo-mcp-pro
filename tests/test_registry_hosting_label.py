"""Hosting label on connection_error analytics events.

Odoo Online and Odoo.sh share the *.odoo.com domain, so the label must use
the server_version 'saas~' marker to separate them (see _hosting_label).
"""

from mcp_server_odoo.registry import _hosting_label


class TestHostingLabel:
    def test_saas_version_is_online(self):
        assert _hosting_label("https://acme.odoo.com", "saas~19.3+e") == "online"

    def test_saas_version_wins_over_custom_domain(self):
        # Online instances can sit behind a custom domain; the version marker
        # is the reliable signal, not the URL.
        assert _hosting_label("https://erp.acme.com", "saas~19.2+e") == "online"

    def test_odoo_com_without_saas_is_sh(self):
        assert _hosting_label("https://acme.odoo.com", "19.0+e") == "sh"

    def test_odoo_com_case_insensitive(self):
        assert _hosting_label("https://Acme.Odoo.COM", None) == "sh"

    def test_custom_domain_is_self_hosted(self):
        assert _hosting_label("https://erp.acme.com", "18.0+e") == "self_hosted"

    def test_none_version_custom_domain(self):
        assert _hosting_label("https://erp.acme.com", None) == "self_hosted"
