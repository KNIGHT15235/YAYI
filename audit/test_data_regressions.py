"""Deterministic data-service regression checks; no external API calls or user writes."""
import asyncio
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend" / "app"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from service.database_explorer import DatabaseExplorer
from service.text2sql_service import Text2SQLService
from service.sql_safety import validate_select
from service.milvus_service import MilvusService, normalize_collection_name
from service.memory_service import MemoryService
from service.docmind_service import chunk_text, process_document_with_docmind


class SQLTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE industry_stats (updated_at TEXT, value INTEGER)"))
            conn.execute(text("INSERT INTO industry_stats VALUES (:updated_at, :value)"),
                         [{"updated_at": "2026-09-21", "value": i} for i in range(150)])
        self.service = Text2SQLService.__new__(Text2SQLService)
        self.service.db_engine = self.engine

    def tearDown(self):
        self.engine.dispose()

    def test_text2sql_caps_existing_limit(self):
        rows, columns, error = self.service.execute_sql("SELECT * FROM industry_stats LIMIT 9999;")
        self.assertIsNone(error)
        self.assertEqual(len(rows), 100)
        self.assertEqual(columns, ["updated_at", "value"])

    def test_explorer_caps_subquery_limit(self):
        with Session(self.engine) as db:
            result = DatabaseExplorer(db).execute_query(
                "SELECT * FROM industry_stats WHERE value IN (SELECT value FROM industry_stats LIMIT 150)", 7)
        self.assertEqual(result["row_count"], 7)

    def test_normal_columns_and_literals(self):
        self.assertTrue(self.service.validate_sql("SELECT updated_at, 'DELETE;--' FROM industry_stats;")[0])

    def test_rejects_writes_and_multiple_statements(self):
        for sql in ["SELECT * INTO sample2 FROM sample", "SELECT 1; SELECT 2", "DROP TABLE sample",
                    "SELECT 1 -- comment", "SELECT 1;;"]:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validate_select(sql)

    def test_no_silent_mock_data(self):
        self.service.db_engine = None
        data, columns, error = self.service.execute_sql("SELECT * FROM industry_stats")
        self.assertEqual(data, [])
        self.assertTrue(error)

    def test_primary_key_parameter_is_bound(self):
        db = Mock()
        db.execute.return_value = []
        DatabaseExplorer(db).get_table_schema("industry_stats")
        pk_query, params = db.execute.call_args_list[1].args
        self.assertIn("table_name", pk_query._bindparams)
        self.assertEqual(params, {"table_name": "public.industry_stats"})


class VectorTests(unittest.TestCase):
    def test_reranker_scores_stay_with_their_original_documents(self):
        from service.chat_service import ChatService
        service = ChatService.__new__(ChatService)
        service.openai_api_key = "test-placeholder"
        def reorder(nodes, query_str):
            nodes[0].score = 0.1
            nodes[1].score = 0.9
            return [nodes[1], nodes[0]]
        with patch("service.chat_service.DashScopeRerank") as rerank:
            rerank.return_value.postprocess_nodes.side_effect = reorder
            scores = service.rerank_similarity("query", [{"content": "irrelevant"}, {"content": "relevant"}])
        self.assertEqual(list(scores), [0.1, 0.9])

    def test_collection_names_are_compatible_and_stable(self):
        self.assertEqual(normalize_collection_name("kb_existing_2026"), "kb_existing_2026")
        name = normalize_collection_name("kb_中文知识库")
        self.assertRegex(name, r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
        self.assertEqual(name, normalize_collection_name("kb_中文知识库"))
        self.assertNotEqual(name, normalize_collection_name("kb_另一个知识库"))

    def test_quoted_filename_expression_and_normalized_collection(self):
        service = MilvusService.__new__(MilvusService)
        collection = Mock()
        collection.query.return_value = []
        with patch("service.milvus_service.utility.has_collection", return_value=True), \
                patch("service.milvus_service.Collection", return_value=collection) as factory:
            service.get_chunks_by_filename("kb_中文知识库", 'a"b.txt')
        factory.assert_called_once_with(normalize_collection_name("kb_中文知识库"))
        self.assertEqual(collection.query.call_args.kwargs["expr"], 'filename == "a\\"b.txt"')

    def test_rename_keeps_old_data_and_refuses_existing_destination(self):
        with patch.object(MilvusService, "_connect"):
            service = MilvusService()
        with patch("service.milvus_service.utility.has_collection", side_effect=[False, True]), \
                patch("service.milvus_service.utility.rename_collection") as rename:
            service.rename_collection("kb_原名", "kb_新名")
        rename.assert_called_once_with(normalize_collection_name("kb_原名"), normalize_collection_name("kb_新名"))
        with patch("service.milvus_service.utility.has_collection", return_value=True), \
                patch("service.milvus_service.utility.rename_collection") as rename:
            with self.assertRaises(ValueError):
                service.rename_collection("kb_old", "kb_existing")
            rename.assert_not_called()


class DocumentTests(unittest.TestCase):
    def test_docmind_business_error_is_preserved_and_file_is_closed(self):
        from service.docmind_service import DocMindService
        service = DocMindService.__new__(DocMindService)
        service.client = Mock()
        service.client.submit_doc_parser_job_advance.return_value = SimpleNamespace(
            body=SimpleNamespace(data=None, code="DocMindServiceNotOpen"))
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sample.pdf"
            file.write_bytes(b"synthetic fixture")
            self.assertIsNone(service.submit_job(str(file), "sample.pdf"))
            self.assertIn("DocMindServiceNotOpen", service.last_error)
            submitted = service.client.submit_doc_parser_job_advance.call_args.args[0]
            self.assertTrue(submitted.file_url_object.closed)

    def test_text_upload_uses_local_parser_then_real_pipeline_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sample.txt"
            file.write_text("这是项目审计使用的虚构文档。", encoding="utf-8")
            with patch("service.docmind_service.DocMindService") as docmind, \
                    patch("service.docmind_service.generate_embedding", return_value=[[0.1] * 1024]), \
                    patch("service.docmind_service.get_milvus_service") as milvus:
                result = process_document_with_docmind(str(file), "sample.txt", "kb_中文知识库")
            docmind.assert_not_called()
            self.assertTrue(result["success"])
            inserted = milvus.return_value.insert_documents.call_args.args[1]
            self.assertEqual(inserted[0]["filename"], "sample.txt")
            self.assertEqual(inserted[0]["content"], "这是项目审计使用的虚构文档。")

    def test_failed_embedding_batch_is_not_inserted(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sample.txt"
            file.write_text("audit", encoding="utf-8")
            with patch("service.docmind_service.generate_embedding", return_value=[None]), \
                    patch("service.docmind_service.get_milvus_service") as milvus:
                result = process_document_with_docmind(str(file), "sample.txt", "kb_audit")
            self.assertFalse(result["success"])
            milvus.assert_not_called()

    def test_chunking_stops_at_end_and_rejects_nonprogressing_overlap(self):
        self.assertEqual(chunk_text("a" * 480), ["a" * 480])
        with self.assertRaises(ValueError):
            chunk_text("abc", chunk_size=50, overlap=50)

    def test_oversized_upload_cleans_temporary_file(self):
        from fastapi import BackgroundTasks, HTTPException, UploadFile
        from router import knowledge_router
        import importlib
        module = importlib.import_module("router.knowledge_router")
        from io import BytesIO
        kb = SimpleNamespace(id=uuid.uuid4(), name="audit_unique")
        db = Mock()
        db.query.return_value.filter.return_value.first.side_effect = [kb, None]
        db.query.return_value.filter.return_value.all.return_value = []
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(module, "UPLOAD_DIR", directory), patch.object(module, "MAX_UPLOAD_SIZE", 3):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(module.upload_document(
                    str(kb.id), BackgroundTasks(), UploadFile(filename="../../a.txt", file=BytesIO(b"audit")),
                    SimpleNamespace(id=uuid.uuid4()), db))
            self.assertEqual(raised.exception.status_code, 413)
            self.assertEqual(list(Path(directory).iterdir()), [])
            db.add.assert_not_called()

    def test_legacy_shared_collection_is_not_deleted(self):
        from fastapi import HTTPException
        from router.knowledge_router import ensure_collection_is_exclusive
        db = Mock()
        db.query.return_value.filter.return_value.all.return_value = [SimpleNamespace(name="AUDIT")]
        with self.assertRaises(HTTPException) as raised:
            ensure_collection_is_exclusive(db, SimpleNamespace(id=uuid.uuid4(), name="audit"))
        self.assertEqual(raised.exception.status_code, 409)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.service = MemoryService.__new__(MemoryService)
        self.service._milvus = None

    def test_first_vector_write_initializes_connection_and_collection(self):
        collection = Mock()
        with patch("service.memory_service.get_milvus_service") as connect, \
                patch.object(self.service, "_ensure_memory_collection") as ensure, \
                patch("service.memory_service.generate_embedding", return_value=[0.1] * 1024), \
                patch("pymilvus.Collection", return_value=collection):
            ids = self.service._store_memory_vectors("m1", "u1", "s1", {"summary": "summary"})
        connect.assert_called_once()
        ensure.assert_called_once()
        self.assertEqual(ids, ["m1_summary"])
        collection.upsert.assert_called_once()

    def test_failed_vector_write_does_not_claim_ids(self):
        collection = Mock()
        collection.upsert.side_effect = RuntimeError("simulated insert failure")
        with patch("service.memory_service.get_milvus_service"), \
                patch.object(self.service, "_ensure_memory_collection"), \
                patch("service.memory_service.generate_embedding", return_value=[0.1] * 1024), \
                patch("pymilvus.Collection", return_value=collection):
            ids = self.service._store_memory_vectors("m1", "u1", "s1", {"summary": "summary"})
        self.assertEqual(ids, [])

    def test_first_retrieval_initializes_milvus(self):
        collection = Mock()
        collection.search.return_value = []
        with patch("service.memory_service.get_milvus_service") as connect, \
                patch.object(self.service, "_ensure_memory_collection"), \
                patch("service.memory_service.generate_embedding", return_value=[0.1] * 1024), \
                patch("pymilvus.Collection", return_value=collection):
            self.assertEqual(self.service._retrieve_vector_memories("u1", "query"), [])
        connect.assert_called_once()
        self.assertEqual(collection.search.call_args.kwargs["expr"], 'user_id == "u1"')

    def test_retrieval_connection_failure_is_graceful(self):
        with patch("service.memory_service.get_milvus_service", side_effect=RuntimeError("offline")):
            self.assertEqual(self.service._retrieve_vector_memories("u1", "query"), [])


class ChatRAGTests(unittest.TestCase):
    def test_nonempty_policy_docs_survive_rerank_fallback_in_both_routes(self):
        from service.chat_service import ChatService
        from router.chat_router import chat_completion_v2, chat_completion_with_attachments
        import importlib
        router_module = importlib.import_module("router.chat_router")
        from schemas.chat import ChatRequest, ChatWithAttachmentsRequest
        service = ChatService.__new__(ChatService)
        service.openai_api_key = "test-placeholder"
        service.openai_base_url = "https://example.invalid"
        service.openai_model = "test-model"
        service.rerank_similarity = Mock(side_effect=RuntimeError("synthetic reranker outage"))
        services = {"chat_service": service, "session_service": Mock(), "default_dataset_id": "fixture"}
        retrieved = [{"id": 1, "content_with_weight": "Synthetic policy fact: 42 units.",
                      "document_name": "fixture.txt", "document_id": "fixture-doc"}]
        expected_doc = {"id": 1, "content": "Synthetic policy fact: 42 units.",
                        "source": "fixture.txt (ID: fixture-doc)", "document_name": "fixture.txt",
                        "document_id": "fixture-doc"}

        async def run_route(version):
            if version == 2:
                response = await chat_completion_v2(ChatRequest(question="question", search_web=False), services, None, Mock())
            else:
                response = await chat_completion_with_attachments(
                    ChatWithAttachmentsRequest(question="question", search_web=False), Mock(), services, None)
            return "".join([part async for part in response.body_iterator])

        for version in (2, 3):
            with self.subTest(version=version), \
                    patch.object(router_module, "retrieve_content", return_value=retrieved), \
                    patch("service.chat_service.OpenAI") as client, patch("builtins.print"):
                client.return_value.chat.completions.create.return_value = [
                    SimpleNamespace(choices=[SimpleNamespace(finish_reason=None, delta=SimpleNamespace(content="42 units"))]),
                    SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]),
                ]
                output = asyncio.run(run_route(version))
                self.assertNotIn("event: error", output)
                self.assertIn("42 units", output)
                self.assertIn("event: end\ndata: [DONE]", output)
                payloads = [json.loads(part[6:]) for part in output.splitlines()
                            if part.startswith("data: {")]
                self.assertEqual(next(p["documents"] for p in payloads if "documents" in p), [expected_doc])
                prompt = client.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("Synthetic policy fact: 42 units.", prompt)


class InMemoryRedis:
    """Small Redis test double for the session persistence calls under test."""
    def __init__(self):
        self.hashes = {}
        self.sorted_sets = {}

    def hset(self, key, field=None, value=None, mapping=None):
        values = mapping if mapping is not None else {field: value}
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in values.items()})

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)

    def zrange(self, key, start, end):
        members = sorted(self.sorted_sets.get(key, {}), key=lambda member: (self.sorted_sets[key][member], member))
        return members[start:] if end == -1 else members[start:end + 1]


class ChatSessionContinuityTests(unittest.TestCase):
    def session_service(self):
        from service.session_service import SessionService
        service = SessionService.__new__(SessionService)
        service.redis_client = InMemoryRedis()
        service.max_messages = 20
        service.token_limit = 5000
        service.encoding = SimpleNamespace(encode=lambda text: list(text))
        return service

    def test_optional_session_id_preserves_legacy_random_ids(self):
        service = self.session_service()
        existing_id = str(uuid.uuid4())
        self.assertEqual(service.create_session(existing_id)["session_id"], existing_id)
        legacy_id = service.create_session()["session_id"]
        another_id = service.create_session(None)["session_id"]
        self.assertNotEqual(legacy_id, existing_id)
        self.assertNotEqual(legacy_id, another_id)
        self.assertEqual(str(uuid.UUID(legacy_id)), legacy_id)

    def test_three_completion_routes_keep_pg_id_and_second_turn_history(self):
        from service.chat_service import ChatService
        from router.chat_router import chat_completion, chat_completion_v2, chat_completion_with_attachments
        from schemas.chat import ChatRequest, ChatWithAttachmentsRequest

        async def call_route(version, services, session_id, question):
            request_class = ChatWithAttachmentsRequest if version == 3 else ChatRequest
            request = request_class(session_id=session_id, question=question, search_web=False, search_knowledge=False)
            if version == 3:
                response = await chat_completion_with_attachments(request, Mock(), services, SimpleNamespace(id=uuid.uuid4()))
            else:
                response = await (chat_completion if version == 1 else chat_completion_v2)(request, services, SimpleNamespace(id=uuid.uuid4()), Mock())
            output = "".join([part async for part in response.body_iterator])
            return request.session_id, output

        for version in (1, 2, 3):
            session = self.session_service()
            chat = ChatService.__new__(ChatService)
            chat.session_service = session
            chat.openai_api_key = "test-placeholder"
            chat.openai_base_url = "https://example.invalid"
            chat.openai_model = "test-model"
            services = {"chat_service": chat, "session_service": session, "default_dataset_id": "fixture"}
            pg_id = str(uuid.uuid4())
            with self.subTest(version=version), \
                    patch.object(session, "create_session", wraps=session.create_session) as create, \
                    patch("service.chat_service.OpenAI") as client, patch("builtins.print"), \
                    patch("service.chat_service.get_memory_service") as memory:
                memory.return_value.build_memory_context.return_value = ""
                client.return_value.chat.completions.create.return_value = [
                    SimpleNamespace(choices=[SimpleNamespace(finish_reason=None, delta=SimpleNamespace(content="synthetic reply"))]),
                    SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")]),
                ]
                first_id, first = asyncio.run(call_route(version, services, pg_id, "first synthetic turn"))
                second_id, second = asyncio.run(call_route(version, services, pg_id, "second synthetic turn"))
                self.assertEqual(first_id, pg_id)
                self.assertEqual(second_id, pg_id)
                create.assert_called_once_with(session_id=pg_id)
                self.assertEqual(len(session.get_history(pg_id)), 4)
                prompt = client.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
                self.assertIn("first synthetic turn", prompt)
                self.assertIn("synthetic reply", prompt)
                self.assertNotIn("event: error", first + second)
                # Omitted IDs remain stateless and do not silently create a new ID.
                none_id, output = asyncio.run(call_route(version, services, None, "stateless turn"))
                self.assertIsNone(none_id)
                create.assert_called_once_with(session_id=pg_id)
                self.assertIn("event: end", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
