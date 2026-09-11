"""Unit tests for POS Troubleshooting RAG Tool helper functions."""

from app.tools.rag_tool import (
    _extract_search_keyword,
    _format_gcs_link,
    _format_rag_response,
    pos_troubleshooting_rag_tool,
)


def test_format_gcs_link() -> None:
    gcs_uri = "gs://daelvate-module1-bucket/store_pos_manual_generic/Toshiba_TCx_810_Guide.pdf"
    expected = "https://storage.cloud.google.com/daelvate-module1-bucket/store_pos_manual_generic/Toshiba_TCx_810_Guide.pdf"
    assert _format_gcs_link(gcs_uri) == expected
    assert _format_gcs_link("") == ""
    assert (
        _format_gcs_link("https://example.com/test.pdf")
        == "https://example.com/test.pdf"
    )


def test_extract_search_keyword() -> None:
    # Error code with hyphens should be quoted with backticks for BigQuery text search
    query = "Cashier encounters an ERR-PAY-4001 EMV contactless payment freeze"
    assert _extract_search_keyword(query) == "`ERR-PAY-4001`"

    # Multi-hyphen error code
    query2 = "Hardware error ERR-DN-PRNT-24V thermal cutter lock"
    assert _extract_search_keyword(query2) == "`ERR-DN-PRNT-24V`"

    # General text query
    query3 = "thermal printer paper jam"
    assert "thermal" in _extract_search_keyword(query3)


def test_format_rag_response() -> None:
    res = _format_rag_response(
        document_title="Toshiba TCx 810 Guide",
        equipment_covered="Toshiba TCx 810 (TGCS Machine Type 6201)",
        source_pdf_uri="gs://my-bucket/doc.pdf",
        retrieval_method="Vector Search",
        score=0.8523,
        stitched_procedure="Step 1: Reboot PIN pad.",
    )
    assert "### 🛠️ Certified POS Troubleshooting Runbook: Toshiba TCx 810 Guide" in res
    assert "https://storage.cloud.google.com/my-bucket/doc.pdf" in res
    assert "Step 1: Reboot PIN pad." in res


def test_empty_query() -> None:
    assert "Query cannot be empty" in pos_troubleshooting_rag_tool("")
    assert "Query cannot be empty" in pos_troubleshooting_rag_tool("   ")
