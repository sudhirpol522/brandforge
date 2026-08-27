import json
import logging
import sys
import time
import types
import unittest
from unittest.mock import patch

from brandforge.exceptions import ValidationError
from brandforge.ingestion import extract_document
from brandforge.security import ValidatedUpload
from brandforge.telemetry import JsonFormatter, MetricsRegistry, Timer, trace_id_var


def upload(media_type: str, content: bytes = b"content") -> ValidatedUpload:
    return ValidatedUpload("guide", media_type, content, "sha256", len(content))


class _Page:
    def __init__(self, text: str | None = None, error: bool = False) -> None:
        self.text = text
        self.error = error

    def extract_text(self) -> str | None:
        if self.error:
            raise RuntimeError("fixture extraction failure")
        return self.text


class _Reader:
    pages = [_Page("Brand voice"), _Page(error=True)]

    def __init__(self, *_args, **_kwargs) -> None:
        self.pages = list(type(self).pages)


class _BrokenReader:
    def __init__(self, *_args, **_kwargs) -> None:
        raise ValueError("malformed fixture")


class IngestionAndTelemetryTests(unittest.TestCase):
    def test_plain_text_and_non_document_assets(self) -> None:
        text = extract_document(upload("text/plain", b"premium and direct"))
        image = extract_document(upload("image/png", b"png"))
        self.assertEqual(text.text, "premium and direct")
        self.assertEqual(text.page_count, 1)
        self.assertIn("no text extractor", image.warnings[0])

    def test_pdf_extraction_records_page_failure(self) -> None:
        fake_pypdf = types.SimpleNamespace(PdfReader=_Reader)
        with patch.dict(sys.modules, {"pypdf": fake_pypdf}):
            result = extract_document(upload("application/pdf", b"%PDF-fixture"))
        self.assertIn("[Page 1]", result.text)
        self.assertEqual(result.page_count, 2)
        self.assertIn("page 2 could not be extracted", result.warnings)

    def test_pdf_page_limit_is_enforced(self) -> None:
        fake_pypdf = types.SimpleNamespace(PdfReader=_Reader)
        with patch.dict(sys.modules, {"pypdf": fake_pypdf}):
            with self.assertRaisesRegex(ValidationError, "page processing limit"):
                extract_document(upload("application/pdf", b"%PDF-fixture"), max_pages=1)

    def test_malformed_pdf_becomes_a_validation_error(self) -> None:
        fake_pypdf = types.SimpleNamespace(PdfReader=_BrokenReader)
        with patch.dict(sys.modules, {"pypdf": fake_pypdf}):
            with self.assertRaisesRegex(ValidationError, "parsed safely"):
                extract_document(upload("application/pdf", b"%PDF-malformed"))

    def test_json_logs_redact_secrets_and_include_trace(self) -> None:
        record = logging.LogRecord(
            "brandforge.test",
            logging.INFO,
            __file__,
            1,
            "api_key=do-not-log",
            (),
            None,
        )
        record.campaign_id = "cmp_test"
        token = trace_id_var.set("trace_test")
        try:
            payload = json.loads(JsonFormatter().format(record))
        finally:
            trace_id_var.reset(token)
        self.assertEqual(payload["trace_id"], "trace_test")
        self.assertEqual(payload["campaign_id"], "cmp_test")
        self.assertNotIn("do-not-log", payload["message"])

    def test_metrics_and_timer_render_prometheus(self) -> None:
        registry = MetricsRegistry()
        registry.increment("campaigns_total", status="created")
        registry.increment("campaigns_total", 2, status="created")
        registry.observe("agent_seconds", 0.5, agent="planner")
        with Timer(registry, "agent_seconds", agent="critic"):
            time.sleep(0.001)

        rendered = registry.render_prometheus()
        self.assertIn('campaigns_total{status="created"} 3.0', rendered)
        self.assertIn('agent_seconds_count{agent="planner"} 1', rendered)
        self.assertIn('agent_seconds_sum{agent="critic"}', rendered)
