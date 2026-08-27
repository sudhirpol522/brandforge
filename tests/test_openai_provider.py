import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from brandforge.exceptions import ValidationError
from brandforge.integrations.openai_provider import OpenAIResponsesProvider


class OpenAIResponsesProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        self.provider.reasoning_effort = "none"
        self.create = Mock()
        self.provider.client = SimpleNamespace(
            responses=SimpleNamespace(create=self.create)
        )

    def test_retries_incomplete_response_with_larger_output_budget(self) -> None:
        self.create.side_effect = [
            SimpleNamespace(
                output_text="",
                status="incomplete",
                incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            ),
            SimpleNamespace(output_text="Campaign copy", status="completed"),
        ]

        response = self.provider._create_response_with_visible_text(
            {"model": "gpt-test", "store": False},
            max_output_tokens=1024,
            output_label="campaign copy",
        )

        self.assertEqual(response.output_text, "Campaign copy")
        self.assertEqual(self.create.call_count, 2)
        self.assertEqual(self.create.call_args_list[0].kwargs["max_output_tokens"], 1024)
        self.assertEqual(self.create.call_args_list[1].kwargs["max_output_tokens"], 4096)
        self.assertEqual(
            self.create.call_args_list[0].kwargs["reasoning"],
            {"effort": "none"},
        )

    def test_reports_sanitized_status_when_response_has_no_text(self) -> None:
        self.create.return_value = SimpleNamespace(
            output_text="",
            status="completed",
            incomplete_details=None,
        )

        with self.assertRaisesRegex(
            ValidationError,
            r"no campaign copy \(status=completed, reason=no_visible_output\)",
        ):
            self.provider._create_response_with_visible_text(
                {"model": "gpt-test", "store": False},
                max_output_tokens=1024,
                output_label="campaign copy",
            )


if __name__ == "__main__":
    unittest.main()
