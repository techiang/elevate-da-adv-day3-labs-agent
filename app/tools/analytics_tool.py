"""Analytics Tool leveraging BigQuery Conversational Data Agent for Cymbal Retail."""

import logging
import os
import time
from typing import Any

import google.adk.tools.data_agent.data_agent_tool as dat
import google.auth
from google.adk.tools.data_agent.config import DataAgentToolConfig
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

# Default resource name of the published BigQuery Conversational Data Agent (Location: global)
DEFAULT_DATA_AGENT_NAME = "projects/daelvate/locations/global/dataAgents/gda-11e81864-7951-4982-9867-6166cd1c0cf5"
DATA_AGENT_NAME = os.getenv("BQ_DATA_AGENT_NAME", DEFAULT_DATA_AGENT_NAME)

FALLBACK_MESSAGE = (
    "Store analytics data is currently unreachable due to temporary connectivity issues. "
    "Please verify network connections or try again later."
)


def _format_data_agent_response(res: dict[str, Any]) -> str:
    """Formats the Data Agent response dictionary into a clean markdown string."""
    if res.get("status") != "SUCCESS":
        error_details = res.get("error_details", "Unknown internal error")
        logger.warning(f"Data Agent returned non-success status: {error_details}")
        return f"{FALLBACK_MESSAGE} (Details: {error_details})"

    output_parts = []
    generated_sqls = []
    retrieved_data = None
    final_summary = []

    for step in res.get("response", []):
        # Extract generated GoogleSQL
        if "data" in step and step["data"].get("generatedSql"):
            generated_sqls.append(step["data"]["generatedSql"])
        # Extract tabular data
        if "Data Retrieved" in step:
            retrieved_data = step["Data Retrieved"]
        # Extract final textual answer
        if "text" in step and step["text"].get("textType") == "FINAL_RESPONSE":
            final_summary.extend(step["text"].get("parts", []))

    if generated_sqls:
        sql_block = "\n;\n".join(generated_sqls)
        output_parts.append(f"**Generated GoogleSQL:**\n```sql\n{sql_block}\n```")

    if retrieved_data:
        headers = retrieved_data.get("headers", [])
        rows = retrieved_data.get("rows", [])
        summary = retrieved_data.get("summary", "")
        if headers:
            table_md = [
                "| " + " | ".join(str(h) for h in headers) + " |",
                "| " + " | ".join(["---"] * len(headers)) + " |",
            ]
            for r in rows[:15]:
                table_md.append("| " + " | ".join(str(val) for val in r) + " |")
            if len(rows) > 15:
                table_md.append(f"*(...showing first 15 of {len(rows)} rows)*")
            output_parts.append(
                "**Data Retrieved:**\n" + "\n".join(table_md) + f"\n\n*{summary}*"
            )

    if final_summary:
        output_parts.append("**Summary:**\n" + "\n".join(final_summary))

    return (
        "\n\n".join(output_parts)
        if output_parts
        else "Query completed with no rows returned."
    )


def cymbal_analytics_tool(query: str) -> str:
    """Queries the Cymbal Retail analytical data layer using BigQuery Conversational Data Agent.

    Use this tool for all relational, structured, and cross-cloud analytics inquiries:
    - Real-time intraday POS checkout revenue and sales KPIs (pos_transactions_gold).
    - Store inventory positions, stockout risks (<20 hours), and on-hand inventory (gold_inventory_reconciliation_ledger).
    - Historical customer transactions and warranty claim lookups (historical_transactional_data and warranty_generic_sections_extracted).
    - Cashier promo abuse anomaly alerts and rankings (pos_anomaly_alerts).
    - Cross-cloud federated AWS S3 historical checkout transaction logs (silver_pos_transactions).
    - Standardized enterprise business terms (Net Transaction Revenue, Total On-Hand Inventory, Estimated Cover Hours, Cashier Promo Override Rate).

    Args:
        query: The natural language analytical question. Pass all terms and questions verbatim without summarizing.

    Returns:
        Structured response containing the generated GoogleSQL, retrieved data rows, and business summary.
    """
    if not query or not query.strip():
        return "Query cannot be empty. Please provide a specific analytical question."

    # Transient fault tolerance with exponential backoff
    max_retries = 3
    initial_delay = 1.0
    backoff_factor = 2.0

    credentials, _ = google.auth.default()
    settings = DataAgentToolConfig()

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            if not credentials.valid:
                credentials.refresh(Request())

            logger.info(
                f"Submitting query to BigQuery Data Agent (attempt {attempt}/{max_retries})"
            )
            res = dat.ask_data_agent(
                DATA_AGENT_NAME,
                query.strip(),
                credentials=credentials,
                settings=settings,
                tool_context=None,
            )

            if res.get("status") == "SUCCESS":
                return _format_data_agent_response(res)

            # If error status returned from API, record and retry if transient
            err_msg = res.get("error_details", "")
            logger.warning(f"Data Agent query returned error: {err_msg}")
            last_error = RuntimeError(err_msg)

        except Exception as exc:
            last_error = exc
            logger.warning(f"Attempt {attempt} failed with exception: {exc}")

        if attempt < max_retries:
            sleep_sec = initial_delay * (backoff_factor ** (attempt - 1))
            logger.info(f"Retrying after {sleep_sec:.1f} seconds...")
            time.sleep(sleep_sec)

    logger.error(f"All {max_retries} attempts failed. Last error: {last_error}")
    return FALLBACK_MESSAGE
