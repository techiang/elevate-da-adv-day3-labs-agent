"""Unit tests for Cloud Bigtable MCP Toolset."""

from unittest.mock import MagicMock, patch

from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StreamableHTTPConnectionParams,
)

from app.tools.bigtable_tool import (
    BIGTABLE_MCP_URL,
    bigtable_mcp_toolset,
    create_authenticated_mcp_client,
    create_bigtable_mcp_toolset,
    get_oidc_id_token,
)


def test_toolset_instantiation() -> None:
    """Tests that bigtable_mcp_toolset is correctly instantiated."""
    assert isinstance(bigtable_mcp_toolset, McpToolset)
    assert isinstance(
        bigtable_mcp_toolset._connection_params, StreamableHTTPConnectionParams
    )
    assert bigtable_mcp_toolset._connection_params.url == f"{BIGTABLE_MCP_URL}/mcp"


def test_create_bigtable_mcp_toolset() -> None:
    """Tests factory function for creating new McpToolset instances."""
    toolset = create_bigtable_mcp_toolset()
    assert isinstance(toolset, McpToolset)
    assert toolset._connection_params.url == f"{BIGTABLE_MCP_URL}/mcp"


def test_cached_oidc_token() -> None:
    """Tests that get_oidc_id_token reuses valid cached tokens."""
    with patch("app.tools.bigtable_tool._CACHED_TOKEN", "mock-valid-token"):
        with patch("app.tools.bigtable_tool._TOKEN_EXPIRY", 9999999999.0):
            token = get_oidc_id_token("https://example-audience.run.app")
            assert token == "mock-valid-token"


def test_create_authenticated_mcp_client_injects_auth() -> None:
    """Tests that create_authenticated_mcp_client injects the Bearer token."""
    with patch(
        "app.tools.bigtable_tool.get_oidc_id_token", return_value="mock-token-xyz"
    ):
        with patch("app.tools.bigtable_tool.create_mcp_http_client") as mock_create:
            mock_create.return_value = MagicMock()
            _ = create_authenticated_mcp_client(headers={"X-Custom": "val"})
            mock_create.assert_called_once()
            called_kwargs = mock_create.call_args.kwargs
            assert called_kwargs["headers"]["Authorization"] == "Bearer mock-token-xyz"
            assert called_kwargs["headers"]["X-Custom"] == "val"
