"""Offline science provenance, identity, persistence and access regressions."""
import asyncio
import base64
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import nullcontext
from uuid import uuid4
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
import models
from models.user import User
from models.knowledge import KnowledgeBase, Document, DocumentAsset, DocumentChunkProvenance
from service import document_assets as assets
from service.docmind_service import DocMindService, process_document_with_docmind, chunk_text
from router import knowledge_router
from schemas.knowledge import KnowledgeSearchRequest


class ParsingTests(unittest.TestCase):
    def test_normalization_keeps_offsets_nested_cells_and_missing_position(self):
        parsed = assets.normalize_layouts([
            {"text": "Intro"},
            {"type": "table", "text": "method 91", "pageNum": [2], "pos": [{"x": 12, "y": 24}],
             "cells": [{"text": "91", "ysc": 3, "yec": 3, "xsc": 1, "xec": 1}]},
            {"type": "formula", "text": "E=mc^2", "equationNumber": "(1)"},
        ], DocMindService._layout_text)
        self.assertEqual(parsed["blocks"][0]["locator"], {})
        self.assertEqual(parsed["assets"][0]["locator"]["page"], [3])
        self.assertEqual(parsed["assets"][0]["locator"]["page_index"], [2])
        cell = next(block for block in parsed["blocks"] if block["locator"].get("row_start") == 3)
        self.assertEqual(parsed["text"][cell["start"]:cell["end"]], "91")
        self.assertEqual(parsed["assets"][1]["locator"]["equation_number"], "(1)")
        self.assertNotIn("page", parsed["assets"][1]["locator"])

    def test_page_id_zero_is_preserved_without_guessing_a_page_number(self):
        self.assertEqual(assets.normalize_locator({"pageId": 0}), {"page_id": 0})

    def test_offsets_are_exact_after_whitespace_and_overlap(self):
        text = "  alpha beta gamma\n" * 40
        chunks = assets.chunk_text_with_offsets(text, 70, 15)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(text[chunk["start"]:chunk["end"]], chunk["content"])
        self.assertEqual(chunk_text(text, 70, 15), [chunk["content"] for chunk in chunks])

    def test_identity_separates_same_name_and_versions(self):
        first, second = uuid4(), uuid4()
        self.assertNotEqual(assets.stable_chunk_id(first, "v1", 0), assets.stable_chunk_id(second, "v1", 0))
        self.assertNotEqual(assets.stable_chunk_id(first, "v1", 0), assets.stable_chunk_id(first, "v2", 0))
        self.assertEqual(assets.stable_chunk_id(first, "v1", 0), assets.stable_chunk_id(first, "v1", 0))

    def test_provider_failure_after_first_page_does_not_become_full_success(self):
        service = DocMindService.__new__(DocMindService)
        def get_page(*args):
            if args[1] == 0:
                return {"layouts": [{"text": "page one"}]}
            service.last_error = "provider failure"
            return None
        service.get_result = get_page
        parsed = service.collect_structured_results("task", 1)
        self.assertEqual(parsed["text"], "page one\n")
        self.assertEqual(parsed["error"], "provider failure")

    def test_new_upload_vectors_use_uuid_and_seven_compatible_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "same.md"
            path.write_text("Research evidence " * 60)
            identity = str(uuid4())
            with patch("service.docmind_service.generate_embedding", side_effect=lambda rows: [[0.1] * 1024 for _ in rows]), patch("service.docmind_service.get_milvus_service") as milvus:
                result = process_document_with_docmind(str(path), "same.md", "kb_science", document_id=identity)
            self.assertTrue(result["success"])
            vectors = milvus.return_value.insert_documents.call_args.args[1]
            self.assertEqual(set(vectors[0]), {"id", "doc_id", "kb_id", "filename", "content", "chunk_index", "vector"})
            self.assertEqual(vectors[0]["doc_id"], identity)
            self.assertEqual(vectors[0]["id"], result["provenance"][0]["chunk_id"])
            self.assertEqual(result["provenance"][0]["locators"], [])

    def test_actual_embedded_image_is_saved_and_unknown_coordinates_stay_empty(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
        parsed = assets.normalize_layouts([{"type": "figure", "text": "Figure caption", "imageBase64": base64.b64encode(buffer.getvalue()).decode()}], DocMindService._layout_text)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DOCUMENT_ASSET_STORAGE_DIR": directory}):
            generated, records, warnings = assets.build_provenance(str(uuid4()), "v1", parsed, assets.chunk_text_with_offsets(parsed["text"]), "unused.pdf")
            self.assertEqual(generated[0]["media_type"], "image/png")
            self.assertTrue(Path(generated[0]["file_path"]).read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(records[0]["locators"], [])
            self.assertEqual(warnings, [])

    def test_untrusted_image_url_is_never_fetched(self):
        with patch("requests.get") as fetch:
            self.assertIsNone(assets._image_bytes({"image_url": "http://127.0.0.1/private", "locator": {}}, "source.txt"))
            fetch.assert_not_called()

    def test_docmind_real_shape_images_are_private_and_captions_are_not_assets(self):
        parsed = assets.normalize_layouts([
            {"type": "figure", "pageNum": 0, "uniqueId": "figure-a", "markdownContent": "![plot](http://example.oss-cn-hangzhou.aliyuncs.com/a.png?Signature=temporary)"},
            {"type": "figure_note", "text": "Fig. 1. Example", "pageNum": 0},
            {"type": "table_name", "text": "TABLE I", "pageNum": 0},
            {"type": "formula", "text": "$$ y=x, (6) $$", "pageNum": 1},
            {"type": "table", "markdownContent": "|Method|F1|\n|---|---|\n|BIT|89.31|", "pageNum": 8},
        ], DocMindService._layout_text)
        self.assertNotIn("Signature", parsed["text"])
        self.assertEqual([asset["type"] for asset in parsed["assets"]], ["image", "equation", "table"])
        self.assertEqual(parsed["assets"][0]["locator"]["page"], 1)
        self.assertEqual(parsed["assets"][0]["locator"]["block_id"], "figure-a")
        self.assertEqual(parsed["assets"][1]["locator"]["equation_number"], "6")
        self.assertEqual(parsed["assets"][2]["locator"]["table_rows"][1]["cells"], ["BIT", "89.31"])

    def test_docmind_nested_cell_layouts_retain_row_text_and_exact_span(self):
        parsed = assets.normalize_layouts([{"type": "table", "pageNum": 8,
            "markdownContent": "| BIT | 89.31 |", "cells": [
                {"ysc": 9, "yec": 9, "xsc": 0, "xec": 0, "layouts": [{"text": "BIT"}]},
                {"ysc": 9, "yec": 9, "xsc": 1, "xec": 1, "layouts": [{"text": "89.31"}]}]}], DocMindService._layout_text)
        cells = parsed["assets"][0]["locator"]["table_rows"]
        self.assertEqual([cell["text"] for cell in cells], ["BIT", "89.31"])
        block = next(block for block in parsed["blocks"] if block["locator"].get("column_start") == 1)
        self.assertEqual(parsed["text"][block["start"]:block["end"]], "89.31")
        self.assertNotIn("table_rows", block["locator"])

    def test_asset_path_cannot_escape_storage(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DOCUMENT_ASSET_STORAGE_DIR": str(Path(directory) / "assets")}):
            outside = Path(directory) / "private.txt"
            outside.write_text("private")
            self.assertIsNone(assets.safe_asset_path(outside))
            assets.remove_asset_files([outside])
            self.assertTrue(outside.exists())


class AssetDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"DOCUMENT_ASSET_STORAGE_DIR": self.directory.name})
        self.environment.start()
        self.engine = create_engine("sqlite:///:memory:")
        @event.listens_for(self.engine, "connect")
        def enable_fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        for model in (User, KnowledgeBase, Document, DocumentAsset, DocumentChunkProvenance):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = User(username="owner", email="owner@test.invalid", hashed_password="unused")
        self.other = User(username="other", email="other@test.invalid", hashed_password="unused")
        self.db.add_all([self.owner, self.other])
        self.db.flush()
        self.kb = KnowledgeBase(name="science", user_id=self.owner.id, document_count=2)
        self.db.add(self.kb)
        self.db.flush()
        self.first = Document(knowledge_base_id=self.kb.id, user_id=self.owner.id, filename="same.pdf", status="completed")
        self.second = Document(knowledge_base_id=self.kb.id, user_id=self.owner.id, filename="same.pdf", status="completed")
        self.db.add_all([self.first, self.second])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.environment.stop()
        self.directory.cleanup()

    def add_assets(self, document):
        parsed = assets.normalize_layouts([{"type": "table", "text": "Method A: 91", "pageNumber": 2, "tableRows": [{"row": 1, "text": "A: 91"}]}], DocMindService._layout_text)
        generated, records, warnings = assets.build_provenance(str(document.id), "v1", parsed, assets.chunk_text_with_offsets(parsed["text"]), "unused.pdf")
        result = {"assets": generated, "provenance": records, "document_version": "v1"}
        assets.persist_provenance(self.db, document, "kb_science", result)
        self.db.commit()
        return result

    def test_two_same_name_documents_keep_distinct_provenance(self):
        first, second = self.add_assets(self.first), self.add_assets(self.second)
        ids = [first["provenance"][0]["chunk_id"], second["provenance"][0]["chunk_id"]]
        enriched = assets.enrich_chunks(self.db, "kb_science", [{"id": key} for key in ids], self.kb.id)
        self.assertEqual([row["document_id"] for row in enriched], [str(self.first.id), str(self.second.id)])
        self.assertEqual(enriched[0]["locators"][0]["page"], 2)
        self.assertNotEqual(enriched[0]["assets"][0]["asset_id"], enriched[1]["assets"][0]["asset_id"])
        self.assertNotIn("file_path", enriched[0]["assets"][0])
        self.assertNotIn("table_rows", enriched[0]["locators"][0])
        self.assertNotIn("table_rows", enriched[0]["assets"][0]["locator"])

    def test_reprocessing_identical_version_is_idempotent(self):
        self.add_assets(self.first)
        self.add_assets(self.first)
        self.assertEqual(self.db.query(DocumentAsset).count(), 1)
        self.assertEqual(self.db.query(DocumentChunkProvenance).count(), 1)

    def test_legacy_chunk_has_empty_optional_fields(self):
        row = assets.enrich_chunks(self.db, "kb_science", [{"id": "legacy", "content": "text", "doc_id": "hash"}], self.kb.id)[0]
        self.assertEqual(row["content"], "text")
        self.assertEqual(row["locators"], [])
        self.assertEqual(row["assets"], [])

    def test_other_collection_or_kb_cannot_enrich_an_asset(self):
        result = self.add_assets(self.first)
        rows = [{"id": result["provenance"][0]["chunk_id"]}]
        self.assertEqual(assets.enrich_chunks(self.db, "kb_other", rows, self.kb.id)[0]["assets"], [])
        self.assertEqual(assets.enrich_chunks(self.db, "kb_science", rows, uuid4())[0]["assets"], [])

    def test_authorized_hydration_has_full_identity_rows_and_version_binding(self):
        result = self.add_assets(self.first)
        rows = [{"id": result["provenance"][0]["chunk_id"], "content": "Method A: 91"}]
        enriched = assets.enrich_chunks(self.db, "kb_science", rows, self.kb.id, hydrate=True, query="Method A")
        self.assertEqual(enriched[0]["knowledge_base_id"], str(self.kb.id))
        self.assertEqual(enriched[0]["document_version"], "v1")
        self.assertTrue(enriched[0]["assets"][0]["locator"]["table_rows"])
        self.assertIn("hydration", enriched[0]["assets"][0])
        asset = self.db.query(DocumentAsset).first()
        asset.document_version = "v2"
        self.db.flush()
        self.assertEqual(assets.enrich_chunks(self.db, "kb_science", rows, self.kb.id, hydrate=True)[0]["assets"], [])

    def test_asset_expansion_checks_owner_document_and_exact_version(self):
        result = self.add_assets(self.first)
        identity = result["assets"][0]["asset_id"]
        value = knowledge_router.get_document_asset_evidence(str(self.kb.id), str(self.first.id), identity,
            document_version="v1", query="Method A", max_chars=5000, current_user=self.owner, db=self.db)
        self.assertEqual(value["document_version"], "v1")
        self.assertTrue(value["locator"]["table_rows"])
        for user, doc, version in [(self.other, self.first, "v1"), (self.owner, self.second, "v1"),
                                    (self.owner, self.first, "v2")]:
            with self.assertRaises(HTTPException) as error:
                knowledge_router.get_document_asset_evidence(str(self.kb.id), str(doc.id), identity,
                    document_version=version, query="", max_chars=5000, current_user=user, db=self.db)
            self.assertEqual(error.exception.status_code, 404)

    def test_research_retrieval_rechecks_owner_before_hydration(self):
        from service.retrieval_service import retrieve_from_knowledge_base
        result = self.add_assets(self.first)
        hits = [{"id": result["provenance"][0]["chunk_id"], "doc_id": str(self.first.id),
                 "content": "Method A: 91", "filename": "same.pdf"}]
        with patch("core.database.SessionLocal", side_effect=lambda: nullcontext(self.db)), \
                patch("service.retrieval_service.search_chunks", return_value={"results": hits}) as search:
            rows = retrieve_from_knowledge_base("science", "Method A", user_id=str(self.owner.id), knowledge_base_id=str(self.kb.id))
            self.assertEqual(rows[0]["knowledge_base_id"], str(self.kb.id))
            self.assertTrue(rows[0]["assets"][0]["locator"]["table_rows"])
            before = search.call_count
            with self.assertRaises(HTTPException):
                retrieve_from_knowledge_base("science", "Method A", user_id=str(self.other.id))
            self.assertEqual(search.call_count, before)
            with self.assertRaises(ValueError):
                retrieve_from_knowledge_base("science", "Method A", user_id=str(self.owner.id), knowledge_base_id=str(uuid4()))
            self.assertEqual(search.call_count, before)

    def test_asset_list_and_download_check_owner_and_document_binding(self):
        result = self.add_assets(self.first)
        identity = result["assets"][0]["asset_id"]
        response = knowledge_router.download_document_asset(str(self.kb.id), str(self.first.id), identity, self.owner, self.db)
        self.assertEqual(response.media_type, "application/json")
        for user, document in [(self.other, self.first), (self.owner, self.second)]:
            with self.assertRaises(HTTPException) as error:
                knowledge_router.download_document_asset(str(self.kb.id), str(document.id), identity, user, self.db)
            self.assertEqual(error.exception.status_code, 404)

    def test_deletion_cascades_metadata_and_removes_asset_files_only(self):
        result = self.add_assets(self.first)
        keep = self.add_assets(self.second)
        with patch("service.milvus_service.get_milvus_service") as milvus:
            milvus.return_value.delete_by_doc_id.return_value = True
            asyncio.run(knowledge_router.delete_document(str(self.kb.id), str(self.first.id), self.owner, self.db))
            self.assertEqual(milvus.return_value.delete_by_doc_id.call_args.args[1], str(self.first.id))
        self.assertEqual(self.db.query(DocumentAsset).count(), 1)
        self.assertEqual(self.db.query(DocumentChunkProvenance).count(), 1)
        self.assertFalse(Path(result["assets"][0]["file_path"]).exists())
        self.assertTrue(Path(keep["assets"][0]["file_path"]).exists())

    def test_legacy_and_new_same_name_search_do_not_share_document_identity(self):
        modern = self.add_assets(self.second)
        hits = [{"id": "legacy", "doc_id": hashlib.md5(self.first.filename.encode()).hexdigest(), "filename": self.first.filename, "content": "old evidence"},
                {"id": modern["provenance"][0]["chunk_id"], "doc_id": str(self.second.id), "filename": self.second.filename, "content": "new evidence"}]
        with patch("service.retrieval_service.search_chunks", return_value={"results": hits, "reranked": False}):
            result = asyncio.run(knowledge_router.search_knowledge_base(str(self.kb.id), KnowledgeSearchRequest(query="evidence"), self.owner, self.db))
        self.assertEqual([row["document_id"] for row in result["results"]], [str(self.first.id), str(self.second.id)])
        with patch("service.milvus_service.get_milvus_service") as milvus:
            milvus.return_value.delete_by_doc_id.return_value = True
            asyncio.run(knowledge_router.delete_document(str(self.kb.id), str(self.first.id), self.owner, self.db))
            self.assertEqual(milvus.return_value.delete_by_doc_id.call_args.args[1], hashlib.md5(self.first.filename.encode()).hexdigest())
        with patch("service.retrieval_service.search_chunks", return_value={"results": hits, "reranked": False}):
            result = asyncio.run(knowledge_router.search_knowledge_base(str(self.kb.id), KnowledgeSearchRequest(query="evidence"), self.owner, self.db))
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["content"], "new evidence")


if __name__ == "__main__":
    unittest.main(verbosity=2)
