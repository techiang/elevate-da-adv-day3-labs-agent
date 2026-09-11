"""POS Hardware Troubleshooting RAG Tool using BigQuery VECTOR_SEARCH and context stitching."""

import logging
import os
import re
import time
from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "daelvate"))
DATASET_ID = "cymbal_gold"
CHUNK_TABLE_NAME = f"{PROJECT_ID}.{DATASET_ID}.pos_manual_chunk_embeddings"
SIMILARITY_THRESHOLD = 0.70

UNCERTIFIED_WARNING = (
    "WARNING: Query appears to be out-of-scope for certified store POS hardware. "
    "No certified procedural runbooks found (relevance score < 0.70). "
    "Please consult Cymbal Retail IT Service Desk or authorized hardware vendor support."
)

FALLBACK_MESSAGE = (
    "POS troubleshooting runbooks are temporarily unreachable due to database connectivity issues. "
    "Please verify network connections or try again later."
)


def _format_gcs_link(gcs_uri: str) -> str:
    """Converts a gs:// URI to a clickable HTTPS Google Cloud Storage link."""
    if not gcs_uri:
        return ""
    if gcs_uri.startswith("gs://"):
        return gcs_uri.replace("gs://", "https://storage.cloud.google.com/")
    return gcs_uri


def _extract_search_keyword(query: str) -> str:
    """Extracts error codes or keywords suitable for BigQuery text SEARCH."""
    # Match error codes with hyphens, e.g. ERR-PAY-4001, ERR-DN-PRNT-24V
    error_codes = re.findall(r"[A-Za-z0-9]+-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", query)
    if error_codes:
        # Enclose in backticks so hyphens are not treated as BigQuery NOT operators
        return f"`{error_codes[0]}`"
    # Otherwise strip non-alphanumeric characters to prevent syntax issues in SEARCH()
    cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", query)
    tokens = [t for t in cleaned.split() if len(t) > 2]
    return " ".join(tokens[:5]) if tokens else query.strip()


def _format_rag_response(
    document_title: str,
    equipment_covered: str,
    source_pdf_uri: str,
    retrieval_method: str,
    score: float | None,
    stitched_procedure: str,
) -> str:
    """Formats retrieved hardware runbook into a clean markdown response."""
    https_link = _format_gcs_link(source_pdf_uri)
    score_str = f"{score:.4f}" if score is not None else "Keyword Fallback Match"

    output_lines = [
        f"### 🛠️ Certified POS Troubleshooting Runbook: {document_title}",
        f"- **Equipment Covered:** {equipment_covered}",
        f"- **Official Manual Link:** [{document_title}]({https_link})",
        f"- **Retrieval Method:** {retrieval_method} (Confidence / Score: {score_str})",
        "",
        "#### 📋 Field Recovery Protocol & Procedural Runbook:",
        stitched_procedure.strip(),
    ]
    return "\n".join(output_lines)


def pos_troubleshooting_rag_tool(query: str) -> str:
    """Searches certified POS terminal hardware manuals and diagnostics runbooks in BigQuery.

    Use this tool to resolve POS terminal hardware issues, peripheral alerts, error codes, and field recovery:
    - POS hardware error codes (e.g., ERR-PAY-4001 EMV contactless payment freeze, ERR-DN-PRNT-24V cutter lock).
    - Barcode scanner, MSR card reader, cash drawer, thermal receipt printer, touch screen, and PIN pad diagnostics.
    - Field recovery protocols for Toshiba TCx 810, HP Engage One Pro, Clover Station Solo, Diebold Nixdorf BEETLE, and NCR Voyix RealPOS.
    - Official certified vendor service documentation links in Cloud Storage.

    Args:
        query: The technical error code, hardware description, or troubleshooting inquiry.

    Returns:
        The certified field recovery protocol and troubleshooting runbook, or an uncertified warning if out-of-scope.
    """
    if not query or not query.strip():
        return (
            "Query cannot be empty. Please provide a POS hardware issue or error code."
        )

    # Exponential backoff parameters
    max_retries = 3
    initial_delay = 1.0
    backoff_factor = 2.0

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            client = bigquery.Client(project=PROJECT_ID)

            # --- Phase 1: Vector Search using BigQuery VECTOR_SEARCH ---
            vector_sql = f"""
            SELECT
                base.document_filename,
                base.chunk_index,
                base.document_title,
                base.equipment_covered,
                base.source_pdf_uri,
                ROUND(1 - distance, 4) AS similarity_score
            FROM VECTOR_SEARCH(
                TABLE `{CHUNK_TABLE_NAME}`,
                "embedding",
                (SELECT AI.EMBED(@query, endpoint => "text-embedding-005").result AS embedding),
                top_k => 1,
                distance_type => "COSINE"
            )
            """
            job_config = QueryJobConfig(
                query_parameters=[
                    ScalarQueryParameter("query", "STRING", query.strip())
                ]
            )
            vector_results = list(
                client.query(vector_sql, job_config=job_config).result()
            )

            matched_chunk: dict[str, Any] | None = None
            retrieval_method = "Vector Similarity Search"
            similarity_score: float | None = None

            if vector_results:
                top_result = vector_results[0]
                similarity_score = float(top_result["similarity_score"])
                logger.info(
                    f"Vector search returned top match: {top_result['document_filename']} "
                    f"(score: {similarity_score})"
                )

                if similarity_score >= SIMILARITY_THRESHOLD:
                    matched_chunk = dict(top_result)

            # --- Phase 2: Full-Text SEARCH Fallback if Vector Similarity < 0.70 ---
            if matched_chunk is None:
                search_term = _extract_search_keyword(query.strip())
                logger.info(
                    f"Vector score below threshold ({similarity_score} < {SIMILARITY_THRESHOLD}). "
                    f"Executing text SEARCH fallback for keyword: '{search_term}'"
                )

                text_sql = f"""
                SELECT
                    document_filename,
                    chunk_index,
                    document_title,
                    equipment_covered,
                    source_pdf_uri
                FROM `{CHUNK_TABLE_NAME}`
                WHERE SEARCH(chunk_content, @search_term)
                LIMIT 1
                """
                text_job_config = QueryJobConfig(
                    query_parameters=[
                        ScalarQueryParameter("search_term", "STRING", search_term)
                    ]
                )
                text_results = list(
                    client.query(text_sql, job_config=text_job_config).result()
                )

                if text_results:
                    matched_chunk = dict(text_results[0])
                    retrieval_method = (
                        f"Exact Keyword SEARCH Fallback ('{search_term}')"
                    )

            # --- Phase 3: Out-of-Scope Guardrail ---
            if matched_chunk is None:
                logger.warning(
                    f"No matching runbooks found for query: '{query[:50]}...'"
                )
                return UNCERTIFIED_WARNING

            # --- Phase 4: Adjacent Context Window Stitching (N-1 to N+1) ---
            doc_filename = matched_chunk["document_filename"]
            chunk_idx = matched_chunk["chunk_index"]

            stitching_sql = f"""
            SELECT
                STRING_AGG(chunk_content, "\\n" ORDER BY chunk_index ASC) AS stitched_procedure
            FROM `{CHUNK_TABLE_NAME}`
            WHERE document_filename = @doc_filename
              AND chunk_index BETWEEN (@chunk_idx - 1) AND (@chunk_idx + 1)
            """
            stitching_config = QueryJobConfig(
                query_parameters=[
                    ScalarQueryParameter("doc_filename", "STRING", doc_filename),
                    ScalarQueryParameter("chunk_idx", "INT64", chunk_idx),
                ]
            )
            stitch_row = next(
                client.query(stitching_sql, job_config=stitching_config).result()
            )
            stitched_text = stitch_row["stitched_procedure"] or ""

            return _format_rag_response(
                document_title=matched_chunk["document_title"],
                equipment_covered=matched_chunk["equipment_covered"],
                source_pdf_uri=matched_chunk["source_pdf_uri"],
                retrieval_method=retrieval_method,
                score=similarity_score,
                stitched_procedure=stitched_text,
            )

        except Exception as exc:
            last_error = exc
            logger.warning(
                f"Attempt {attempt}/{max_retries} failed for RAG query: {exc}"
            )

            if attempt < max_retries:
                sleep_sec = initial_delay * (backoff_factor ** (attempt - 1))
                time.sleep(sleep_sec)

    logger.error(
        f"All {max_retries} attempts failed for RAG tool. Last error: {last_error}"
    )
    return FALLBACK_MESSAGE
