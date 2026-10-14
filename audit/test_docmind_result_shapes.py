"""DocMind OCR result-shape regressions. No network or paid submissions."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from service.docmind_service import DocMindService


class ResultShapeTests(unittest.TestCase):
    def parse(self, value, step=10):
        service = DocMindService.__new__(DocMindService)
        service.get_result = Mock(return_value=value)
        return service, service.collect_all_results("synthetic-job", step)

    def test_markdown_has_precedence_without_duplicate_text(self):
        _, text = self.parse({"layouts": [{"markdownContent": "# OCR 7342", "text": "OCR 7342", "blocks": [{"text": "OCR 7342"}]}]})
        self.assertEqual(text, "# OCR 7342\n")

    def test_sdk_attributes_with_snake_case_fields(self):
        _, text = self.parse(SimpleNamespace(layouts=[SimpleNamespace(markdown_content="OCR 7342")]))
        self.assertEqual(text, "OCR 7342\n")

    def test_json_string_and_data_envelope(self):
        _, text = self.parse(json.dumps({"Data": {"layouts": [{"text": "OCR 7342"}]}}))
        self.assertEqual(text, "OCR 7342\n")

    def test_pascal_case_model_mapping(self):
        model = SimpleNamespace(to_map=lambda: {"Layouts": [{"MarkdownContent": "OCR 7342"}]})
        _, text = self.parse(model)
        self.assertEqual(text, "OCR 7342\n")

    def test_nested_ocr_blocks_and_cells(self):
        _, text = self.parse({"layouts": [{"blocks": [{"text": "OCR"}, {"cells": [{"text": "7342"}]}]}]})
        self.assertEqual(text, "OCR\n7342\n")

    def test_whitespace_markdown_falls_back_to_plain_text(self):
        _, text = self.parse({"layouts": [{"markdownContent": " \n", "text": "OCR 7342"}]})
        self.assertEqual(text, "OCR 7342\n")

    def test_vlm_result_when_layout_has_no_plain_text(self):
        _, text = self.parse({"layouts": [{"llmResult": "| Audit | 7342 |"}]})
        self.assertEqual(text, "| Audit | 7342 |\n")

    def test_pagination_advances_by_layout_count(self):
        service = DocMindService.__new__(DocMindService)
        service.get_result = Mock(side_effect=[{"layouts": [{"text": "first"}, {"blocks": [{"text": "second"}]}]},
                                              {"layouts": [{"text": "third"}]}])
        self.assertEqual(service.collect_all_results("synthetic-job", 2), "first\nsecond\nthird\n")
        self.assertEqual(service.get_result.call_args_list[1].args, ("synthetic-job", 2, 2))

    def test_real_empty_layout_shape_is_not_fabricated_as_success(self):
        service, text = self.parse({"layouts": []})
        self.assertEqual(text, "")
        self.assertIn("未返回可识别正文", service.last_error)

    def test_invalid_json_does_not_become_ocr_text(self):
        service, text = self.parse('{"layouts":')
        self.assertEqual(text, "")
        self.assertIsNotNone(service.last_error)

    def test_vlm_ocr_is_scoped_to_images_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-file"
            path.write_bytes(b"synthetic test bytes; network client mocked")
            for filename, enabled, expected in [("scan.PNG", "true", True), ("report.pdf", "true", False),
                                                ("scan.png", "false", False)]:
                with self.subTest(filename=filename, enabled=enabled), patch.dict(os.environ, {"DOCMIND_IMAGE_VLM_ENABLED": enabled}):
                    service = DocMindService.__new__(DocMindService)
                    service.client = Mock()
                    service.client.submit_doc_parser_job_advance.return_value = SimpleNamespace(body=SimpleNamespace(data=SimpleNamespace(id="synthetic-job")))
                    self.assertEqual(service.submit_job(str(path), filename), "synthetic-job")
                    request = service.client.submit_doc_parser_job_advance.call_args.args[0]
                    self.assertEqual(request.llm_enhancement, True if expected else None)
                    self.assertEqual(request.enhancement_mode, "VLM" if expected else None)
                    self.assertEqual(request.need_header_footer, True if expected else None)
                    self.assertTrue(request.file_url_object.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
