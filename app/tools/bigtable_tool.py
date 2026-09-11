"""Cloud Bigtable MCP Toolset connecting to the Cloud Run microservice with OIDC auth."""

import logging
import os
import subprocess
import time

import google.auth
import google.oauth2.id_token
import httpx
from google.adk.tools.mcp_tool.mcp_session_manager import create_mcp_http_client
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StreamableHTTPConnectionParams,
)
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

DEFAULT_BIGTABLE_MCP_URL = (
    "https://mcp-toolbox-bigtable-563408139689.us-central1.run.app"
)
BIGTABLE_MCP_URL = os.getenv(
    "BIGTABLE_MCP_URL",
    os.getenv("BIGTABLE_MCP_SERVICE_URL", DEFAULT_BIGTABLE_MCP_URL),
).rstrip("/")
BIGTABLE_MCP_INVOKER_SA = os.getenv(
    "BIGTABLE_MCP_INVOKER_SA", "cymbal-sa-data@daelvate.iam.gserviceaccount.com"
)

# In-memory cached token to avoid generating new tokens on every request
_CACHED_TOKEN: str | None = None
_TOKEN_EXPIRY: float = 0.0


def get_oidc_id_token(audience: str) -> str:
    """Acquires a valid GCP OIDC ID token for the specified Cloud Run audience.

    Attempts several discovery methods in priority order:
    1. Cached valid token.
    2. Service account impersonation using Application Default Credentials (ADC).
    3. Direct OIDC token fetch via google.oauth2.id_token (standard on Compute Engine / Cloud Run).
    4. gcloud CLI fallback.
    """
    global _CACHED_TOKEN, _TOKEN_EXPIRY

    now = time.time()
    # Return cached token if valid for at least another 5 minutes
    if _CACHED_TOKEN and now < (_TOKEN_EXPIRY - 300):
        return _CACHED_TOKEN

    # Method 1: Impersonated credentials targeting the assigned service account
    try:
        source_creds, _ = google.auth.default()
        impersonated_sa = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=BIGTABLE_MCP_INVOKER_SA,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        id_creds = impersonated_credentials.IDTokenCredentials(
            target_credentials=impersonated_sa,
            target_audience=audience,
        )
        id_creds.refresh(Request())
        if id_creds.token:
            _CACHED_TOKEN = id_creds.token
            _TOKEN_EXPIRY = (
                id_creds.expiry.timestamp() if id_creds.expiry else (now + 3600)
            )
            return _CACHED_TOKEN
    except Exception as e:
        logger.debug(f"Impersonation token acquisition failed: {e}")

    # Method 2: Direct fetch_id_token (e.g. running in Cloud Run / GCE with instance service account)
    try:
        auth_req = Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, audience)
        if token:
            _CACHED_TOKEN = token
            _TOKEN_EXPIRY = now + 3600
            return _CACHED_TOKEN
    except Exception as e:
        logger.debug(f"Direct fetch_id_token failed: {e}")

    # Method 3: gcloud CLI fallback
    try:
        cmd = ["gcloud", "auth", "print-identity-token", f"--audiences={audience}"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        token = res.stdout.strip()
        if token:
            _CACHED_TOKEN = token
            _TOKEN_EXPIRY = now + 3600
            return _CACHED_TOKEN
    except Exception as e:
        logger.debug(f"gcloud print-identity-token fallback failed: {e}")

    raise RuntimeError(
        f"Unable to acquire OIDC ID token for Cloud Run MCP service: {audience}. "
        "Please ensure gcloud is authenticated or ADC has access to impersonate the service account."
    )


def create_authenticated_mcp_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Factory creating an HTTPX AsyncClient with fresh OIDC ID token in Authorization header."""
    token = get_oidc_id_token(BIGTABLE_MCP_URL)
    merged_headers = dict(headers or {})
    merged_headers["Authorization"] = f"Bearer {token}"
    return create_mcp_http_client(
        headers=merged_headers,
        timeout=timeout,
        auth=auth,
    )


def create_bigtable_mcp_toolset() -> McpToolset:
    """Creates an McpToolset configured for the Bigtable MCP Cloud Run service."""
    mcp_endpoint = f"{BIGTABLE_MCP_URL}/mcp"
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_endpoint,
            httpx_client_factory=create_authenticated_mcp_client,
        ),
    )


# Globally instantiated toolset instance ready for coordinator agent binding
bigtable_mcp_toolset: McpToolset = create_bigtable_mcp_toolset()

__all__ = [
    "BIGTABLE_MCP_URL",
    "bigtable_mcp_toolset",
    "create_authenticated_mcp_client",
    "create_bigtable_mcp_toolset",
    "get_oidc_id_token",
]
