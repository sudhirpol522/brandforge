import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from brandforge.config import Settings
from brandforge.factory import build_workflow


class ConfigAndFactoryTests(unittest.TestCase):
    def test_settings_parse_environment_and_database_parts(self) -> None:
        environment = {
            "BRANDFORGE_ENV": "test",
            "BRANDFORGE_DEV_AUTH": "off",
            "DB_HOST": "database.internal",
            "DB_USER": "brand user",
            "DB_PASSWORD": "p@ss/word",
            "DB_PORT": "5433",
            "DB_NAME": "brand forge",
            "ALLOWED_ORIGINS": "https://one.example, https://two.example,",
            "MODEL_MAX_CALLS_PER_CAMPAIGN": "12",
            "MODEL_REQUEST_BUDGET_USD": "1.25",
            "OPENAI_REASONING_EFFORT": "low",
            "OPENAI_TEXT_MAX_OUTPUT_TOKENS": "2048",
            "OPENAI_VISION_MAX_OUTPUT_TOKENS": "3072",
            "MAX_UPLOAD_BYTES": "1024",
            "ADOBE_FIREFLY_ENABLED": "yes",
        }
        with patch.dict("os.environ", environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.environment, "test")
        self.assertFalse(settings.dev_auth)
        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg://brand+user:p%40ss%2Fword@database.internal:5433/brand+forge",
        )
        self.assertEqual(settings.allowed_origins, ("https://one.example", "https://two.example"))
        self.assertEqual(settings.model_max_calls_per_campaign, 12)
        self.assertEqual(settings.model_request_budget_usd, 1.25)
        self.assertEqual(settings.openai_reasoning_effort, "low")
        self.assertEqual(settings.openai_text_max_output_tokens, 2048)
        self.assertEqual(settings.openai_vision_max_output_tokens, 3072)
        self.assertEqual(settings.max_upload_bytes, 1024)
        self.assertTrue(settings.adobe_firefly_enabled)

    def test_explicit_database_url_wins(self) -> None:
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "sqlite:///custom.db", "DB_HOST": "ignored"},
            clear=True,
        ):
            self.assertEqual(Settings.from_env().database_url, "sqlite:///custom.db")

    def test_local_deterministic_workflow_is_wired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                database_url=f"sqlite:///{root / 'brandforge.db'}",
                local_object_store_path=str(root / "objects"),
            )
            workflow = build_workflow(settings)

            self.assertEqual(workflow.creative.gateway.provider.name, "deterministic")
            self.assertEqual(workflow.exporter.object_store.root, (root / "objects").resolve())

    def test_factory_rejects_unknown_store_and_provider(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported object store"):
            build_workflow(replace(Settings(), object_store_provider="unknown"))
        with tempfile.TemporaryDirectory() as directory:
            base = Settings(
                database_url=f"sqlite:///{Path(directory) / 'brandforge.db'}",
                local_object_store_path=str(Path(directory) / "objects"),
            )
            with self.assertRaisesRegex(ValueError, "unsupported model provider"):
                build_workflow(replace(base, model_provider="unknown"))
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                build_workflow(replace(base, model_provider="openai"))
            with self.assertRaisesRegex(ValueError, "OPENAI_BASE_URL"):
                build_workflow(replace(base, model_provider="openai-compatible"))

    def test_remote_retrieval_keeps_openclip_out_of_api_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                database_url=f"sqlite:///{root / 'brandforge.db'}",
                local_object_store_path=str(root / "objects"),
                retrieval_enabled=True,
                retrieval_embedding_provider="remote",
                retrieval_remote_url="http://multimodal-worker:8010",
                retrieval_embedding_dimension=512,
            )
            workflow = build_workflow(settings)
            self.assertIsNotNone(workflow.retrieval)
            assert workflow.retrieval is not None
            self.assertEqual(workflow.retrieval.embeddings.dimension, 512)

    def test_openai_key_selects_the_official_sdk_adapter_without_a_network_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                database_url=f"sqlite:///{root / 'brandforge.db'}",
                local_object_store_path=str(root / "objects"),
                model_provider="openai",
                openai_api_key="test-key-never-sent",
            )
            workflow = build_workflow(settings)
            provider = workflow.creative.gateway.provider
            try:
                self.assertEqual(provider.name, "openai")
                self.assertEqual(provider.model_name, settings.openai_text_model)
                self.assertEqual(
                    provider.text_max_output_tokens,
                    settings.openai_text_max_output_tokens,
                )
                self.assertEqual(
                    provider.vision_max_output_tokens,
                    settings.openai_vision_max_output_tokens,
                )
                self.assertEqual(provider.reasoning_effort, settings.openai_reasoning_effort)
            finally:
                provider.client.close()
