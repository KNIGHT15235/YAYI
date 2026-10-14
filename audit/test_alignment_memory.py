"""Real isolated PG/Redis integration with mocked LLM/embedding; no paid API calls."""
import asyncio
import json
import os
import sys
import time
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env")
from core.database import SessionLocal
from models import User, ChatSession, ChatMessage, LongTermMemory
from service.memory_service import MemoryService, MemoryGenerationError, MemoryBusyError, estimate_memory_tokens
from service import memory_jobs as jobs


class MemoryAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.prefix = "audit_alignment_memory:" + uuid.uuid4().hex
        self.settings = patch.dict(os.environ, {"MEMORY_AUTO_ENABLED": "true", "MEMORY_VECTOR_ENABLED": "false", "MEMORY_TOKEN_THRESHOLD": "10", "MEMORY_MAX_RETRIES": "2"})
        self.settings.start()
        self.patches = [patch.object(jobs, "PREFIX", self.prefix), patch.object(jobs, "SUMMARY_JOBS", self.prefix + ":summary_jobs"),
                        patch.object(jobs, "INDEX_JOBS", self.prefix + ":index_jobs")]
        for item in self.patches:
            item.start()
        self.cache = jobs.memory_cache()
        self.db = SessionLocal()
        self.uid = uuid.uuid4()
        self.sid = uuid.uuid4()
        self.db.add(User(id=self.uid, username="audit_mem_" + self.uid.hex, email=self.uid.hex + "@example.com", hashed_password="synthetic-unusable-password"))
        self.db.add(ChatSession(id=self.sid, user_id=self.uid, title="Synthetic memory test"))
        self.db.commit()
        self.service = MemoryService.__new__(MemoryService)
        self.service._milvus = None
        self.service.summarize_conversation = Mock(side_effect=lambda rows: {
            "summary": "新能源汽车销量 synthetic summary", "key_insights": [],
            "user_preferences": {"communication_style": "中文表格"}, "topics": [],
        })
        self.factory = patch("service.memory_service.get_memory_service", return_value=self.service)
        self.factory.start()

    def tearDown(self):
        self.db.rollback()
        self.db.query(LongTermMemory).filter(LongTermMemory.user_id == self.uid).delete(synchronize_session=False)
        self.db.query(ChatMessage).filter(ChatMessage.session_id == self.sid).delete(synchronize_session=False)
        self.db.query(ChatSession).filter(ChatSession.id == self.sid).delete(synchronize_session=False)
        self.db.query(User).filter(User.id == self.uid).delete(synchronize_session=False)
        self.db.commit()
        self.db.close()
        keys = list(self.cache.scan_iter(match=self.prefix + ":*"))
        if keys:
            self.cache.delete(*keys)
        self.factory.stop()
        for item in reversed(self.patches):
            item.stop()
        self.settings.stop()

    def message(self, content="synthetic new message " * 3):
        row = ChatMessage(id=uuid.uuid4(), session_id=self.sid, role="user", content=content)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def enqueue(self, row):
        return jobs.enqueue_message(self.uid, self.sid, row.id, row.content, row.created_at)

    def test_manual_dedup_and_incremental_messages(self):
        first = self.message()
        memory = self.service.create_memory(self.db, str(self.uid), str(self.sid), [first])
        again = self.service.create_memory(self.db, str(self.uid), str(self.sid), [first])
        self.assertEqual(memory.id, again.id)
        self.assertEqual(self.service.summarize_conversation.call_count, 1)
        self.db.commit()  # release the duplicate-save advisory transaction lock
        second = self.message("new preference: use tables")
        newer = self.service.create_memory(self.db, str(self.uid), str(self.sid), [first, second])
        self.assertEqual(newer.key_insights["_source_message_ids"], [str(second.id)])
        self.assertEqual(self.service.summarize_conversation.call_count, 2)

    def test_threshold_only_enrolls_new_rows_not_history(self):
        old = self.message("pre-existing history never enrolled")
        new = self.message()
        self.assertTrue(self.enqueue(new))
        self.assertTrue(self.enqueue(new))  # registering same message is idempotent
        key = f"{self.prefix}:session:{self.sid}"
        self.assertEqual(int(self.cache.hget(key, "tokens")), estimate_memory_tokens(new.content))
        self.assertEqual(jobs.process_session(str(self.sid))["status"], "completed")
        self.db.expire_all()
        row = self.db.query(LongTermMemory).filter(LongTermMemory.user_id == self.uid).one()
        self.assertEqual(row.key_insights["_source_message_ids"], [str(new.id)])
        self.assertNotIn(str(old.id), row.key_insights["_source_message_ids"])
        self.assertEqual(self.cache.zcard(jobs.SUMMARY_JOBS), 0)

    def test_periodic_small_conversation_and_disabled_gate(self):
        row = self.message("small")
        with patch.dict(os.environ, {"MEMORY_AUTO_ENABLED": "false"}):
            self.assertFalse(self.enqueue(row))
        self.assertEqual(self.cache.zcard(jobs.SUMMARY_JOBS), 0)
        self.assertFalse(self.enqueue(row))
        jobs.run_due_jobs()
        self.service.summarize_conversation.assert_not_called()
        self.cache.zadd(jobs.SUMMARY_JOBS, {str(self.sid): time.time() - 1})
        jobs.run_due_jobs()
        self.service.summarize_conversation.assert_called_once()

    def test_failed_summary_retains_queue_and_retries_without_placeholder(self):
        row = self.message()
        self.enqueue(row)
        self.service.summarize_conversation.side_effect = [MemoryGenerationError("synthetic failure"),
            {"summary": "successful retry", "key_insights": [], "user_preferences": {}, "topics": []}]
        self.assertEqual(jobs.process_session(str(self.sid))["status"], "retry")
        self.assertEqual(self.db.query(LongTermMemory).filter(LongTermMemory.user_id == self.uid).count(), 0)
        self.assertEqual(self.cache.zcard(f"{self.prefix}:session:{self.sid}:messages"), 1)
        self.assertEqual(jobs.process_session(str(self.sid))["status"], "completed")
        self.assertEqual(self.service.summarize_conversation.call_count, 2)

    def test_pg_lock_blocks_parallel_duplicate_paid_call(self):
        row = self.message()
        # First caller obtains the lock and deliberately leaves its transaction open.
        import hashlib
        from sqlalchemy import text
        key = int.from_bytes(hashlib.sha256(f"{self.uid}:{self.sid}".encode()).digest()[:8], "big", signed=True)
        self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        with SessionLocal() as second:
            with self.assertRaises(MemoryBusyError):
                self.service.create_memory(second, str(self.uid), str(self.sid), [row])
        self.service.summarize_conversation.assert_not_called()

    def test_keyword_recall_works_without_embeddings_and_includes_preferences(self):
        row = self.message()
        memory = self.service.create_memory(self.db, str(self.uid), str(self.sid), [row])
        with patch.object(self.service, "_retrieve_vector_memories") as vector:
            results = self.service.retrieve_memories(str(self.uid), "新能源汽车销量", db=self.db)
        vector.assert_not_called()
        self.assertEqual(results[0]["id"], str(memory.id))
        self.assertIn("中文表格", results[0]["content"])
        self.assertEqual(self.service.retrieve_memories(str(uuid.uuid4()), "新能源汽车销量", db=self.db), [])
        memory.summary = "Synthetic ELECTRIC VEHICLES trend"
        self.db.commit()
        self.assertEqual(self.service.retrieve_memories(str(self.uid), "electric vehicles", db=self.db)[0]["id"], str(memory.id))

    def test_hybrid_fusion_deduplicates_and_rejects_foreign_vector_ids(self):
        row = self.message()
        memory = self.service.create_memory(self.db, str(self.uid), str(self.sid), [row])
        memory.milvus_ids = [str(memory.id) + "_summary"]
        self.db.commit()
        hits = [{"id": str(memory.id) + "_summary", "metadata": json.dumps({"memory_id": str(memory.id)}), "score": 1},
                {"id": str(memory.id) + "_insight_0", "metadata": json.dumps({"memory_id": str(memory.id)}), "score": .8},
                {"id": str(uuid.uuid4()) + "_summary", "metadata": "{}", "score": .9}]
        with patch.dict(os.environ, {"MEMORY_VECTOR_ENABLED": "true"}), \
                patch.object(self.service, "_retrieve_vector_memories", return_value=hits):
            results = self.service.retrieve_memories(str(self.uid), "新能源汽车销量", db=self.db)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(memory.id))
        self.assertGreater(results[0]["score"], .5)

    def test_index_retry_never_repeats_summary(self):
        row = self.message()
        with patch.dict(os.environ, {"MEMORY_VECTOR_ENABLED": "true"}), \
                patch.object(self.service, "_store_memory_vectors", side_effect=[[], ["synthetic-id"]]) as store:
            memory = self.service.create_memory(self.db, str(self.uid), str(self.sid), [row])
            self.assertEqual(jobs.process_index(str(memory.id))["status"], "retry")
            self.assertEqual(jobs.process_index(str(memory.id))["status"], "completed")
        self.service.summarize_conversation.assert_called_once()
        self.db.refresh(memory)
        self.assertEqual(memory.key_insights["_indexing_status"], "completed")

    def test_chat_owner_checks_and_memory_context_injection(self):
        from router.chat_router import authorize_chat_session, chat_completion_with_attachments
        from schemas.chat import ChatWithAttachmentsRequest
        from fastapi import HTTPException
        request = ChatWithAttachmentsRequest(session_id=str(self.sid), question="新能源汽车销量", search_knowledge=False, search_web=False)
        with self.assertRaises(HTTPException) as denied:
            authorize_chat_session(request, SimpleNamespace(id=uuid.uuid4()), self.db)
        self.assertEqual(denied.exception.status_code, 404)
        chat = Mock()
        chat.get_chat_completion.return_value = iter(["event: end\ndata: [DONE]\n\n"])
        sessions = Mock()
        async def run():
            response = await chat_completion_with_attachments(request, self.db, {"chat_service": chat, "session_service": sessions}, SimpleNamespace(id=self.uid))
            return [part async for part in response.body_iterator]
        asyncio.run(run())
        self.assertEqual(chat.get_chat_completion.call_args.kwargs["user_id"], str(self.uid))

    def test_authenticated_message_endpoint_triggers_background_compression(self):
        from fastapi import BackgroundTasks
        from router.session_router import add_message
        from schemas.chat import MessageCreate
        tasks = BackgroundTasks()
        response = asyncio.run(add_message(str(self.sid), MessageCreate(role="user", content="new endpoint text " * 5),
                                           tasks, SimpleNamespace(id=self.uid), self.db))
        self.assertEqual(len(tasks.tasks), 1)
        asyncio.run(tasks())
        memory = self.db.query(LongTermMemory).filter(LongTermMemory.user_id == self.uid).one()
        self.assertEqual(memory.key_insights["_source_message_ids"], [response.id])

    def test_manual_model_failure_returns_503_without_fake_memory(self):
        from fastapi import BackgroundTasks, HTTPException
        from router.memory_router import create_memory_from_session, CreateMemoryRequest
        self.message()
        self.service.summarize_conversation.side_effect = MemoryGenerationError("synthetic failure")
        with self.assertRaises(HTTPException) as caught:
            create_memory_from_session(CreateMemoryRequest(session_id=str(self.sid)), BackgroundTasks(), SimpleNamespace(id=self.uid), self.db)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.db.query(LongTermMemory).filter(LongTermMemory.user_id == self.uid).count(), 0)

    def test_bounded_retry_stops_without_dropping_new_message_ids(self):
        row = self.message()
        self.enqueue(row)
        self.service.summarize_conversation.side_effect = MemoryGenerationError("synthetic outage")
        jobs.process_session(str(self.sid))
        jobs.process_session(str(self.sid))
        self.assertEqual(self.cache.zcard(jobs.SUMMARY_JOBS), 0)
        self.assertEqual(self.cache.zcard(f"{self.prefix}:session:{self.sid}:messages"), 1)
        jobs.run_due_jobs()
        self.assertEqual(self.service.summarize_conversation.call_count, 2)

    def test_job_rechecks_owner_and_does_not_process_foreign_messages(self):
        row = self.message()
        self.enqueue(row)
        self.cache.hset(f"{self.prefix}:session:{self.sid}", "user_id", str(uuid.uuid4()))
        self.assertEqual(jobs.process_session(str(self.sid))["status"], "removed")
        self.service.summarize_conversation.assert_not_called()

    def test_explicit_kb_selection_requires_authenticated_owner(self):
        from fastapi import HTTPException
        from router.chat_router import selected_knowledge_collection
        from schemas.chat import ChatRequest
        request = ChatRequest(question="query", kb_name="synthetic-private-kb", search_knowledge=True)
        with self.assertRaises(HTTPException) as caught:
            selected_knowledge_collection(request, None, self.db)
        self.assertEqual(caught.exception.status_code, 401)
        with self.assertRaises(HTTPException) as caught:
            selected_knowledge_collection(request, SimpleNamespace(id=self.uid), self.db)
        self.assertEqual(caught.exception.status_code, 404)

    def test_deleted_session_discards_queue_and_cannot_trigger_model(self):
        from router.session_router import delete_session
        row = self.message()
        self.enqueue(row)
        asyncio.run(delete_session(str(self.sid), SimpleNamespace(id=self.uid), self.db))
        self.assertEqual(self.cache.zcard(jobs.SUMMARY_JOBS), 0)
        self.assertEqual(self.cache.zcard(f"{self.prefix}:session:{self.sid}:messages"), 0)
        jobs.run_due_jobs()
        self.service.summarize_conversation.assert_not_called()

    def test_worker_removes_stale_deleted_session_before_model(self):
        row = self.message()
        self.enqueue(row)
        self.db.query(ChatMessage).filter(ChatMessage.session_id == self.sid).delete(synchronize_session=False)
        self.db.query(ChatSession).filter(ChatSession.id == self.sid).delete(synchronize_session=False)
        self.db.commit()
        self.assertEqual(jobs.process_session(str(self.sid))["status"], "removed")
        self.assertEqual(self.cache.zcard(jobs.SUMMARY_JOBS), 0)
        self.service.summarize_conversation.assert_not_called()

    def test_memory_context_switch_prevents_recall(self):
        from service.chat_service import ChatService
        service = ChatService.__new__(ChatService)
        service.openai_api_key = "synthetic"
        service.openai_base_url = "http://synthetic.invalid"
        service.openai_model = "synthetic"
        client = Mock()
        client.chat.completions.create.return_value = iter([])
        with patch.dict(os.environ, {"MEMORY_CONTEXT_ENABLED": "false"}), \
                patch("service.chat_service.OpenAI", return_value=client), \
                patch("service.chat_service.get_memory_service") as recall, patch("builtins.print"):
            list(service.get_chat_completion(None, "synthetic", [], user_id=str(self.uid)))
        recall.assert_not_called()

    def test_token_estimate_uses_shared_encoder_and_accepts_special_text(self):
        import tiktoken
        content = "中文 test <|endoftext|>"
        self.assertEqual(estimate_memory_tokens(content), len(tiktoken.get_encoding("cl100k_base").encode(content, disallowed_special=())))

    def test_large_message_resumes_without_losing_unprocessed_tail(self):
        content = "合成超长消息 synthetic content. " * 2500
        row = self.message(content)
        self.enqueue(row)
        self.assertEqual(jobs.process_session(str(self.sid))["status"], "completed")
        first = self.db.query(LongTermMemory).filter(LongTermMemory.user_id == self.uid).one()
        self.assertEqual(first.key_insights["_source_message_ids"], [])
        self.assertTrue(first.key_insights["_has_more_messages"])
        self.assertEqual(self.cache.zcard(f"{self.prefix}:session:{self.sid}:messages"), 1)
        for _ in range(4):
            if not self.cache.zcard(jobs.SUMMARY_JOBS):
                break
            jobs.process_session(str(self.sid))
        self.assertEqual(self.cache.zcard(jobs.SUMMARY_JOBS), 0)
        pieces = [msg.content for call in self.service.summarize_conversation.call_args_list for msg in call.args[0]]
        self.assertEqual("".join(pieces), content)
        self.assertTrue(all(len(piece) <= 29995 for piece in pieces))

    def test_batch_keeps_later_messages_in_queue(self):
        first = self.message("a synthetic first message " * 800)
        second = self.message("b synthetic second message " * 800)
        self.enqueue(first)
        self.enqueue(second)
        jobs.process_session(str(self.sid))
        remaining = self.cache.zrange(f"{self.prefix}:session:{self.sid}:messages", 0, -1)
        self.assertEqual(remaining, [str(second.id)])
        jobs.process_session(str(self.sid))
        self.assertEqual(self.cache.zcard(jobs.SUMMARY_JOBS), 0)
        pieces = [msg.content for call in self.service.summarize_conversation.call_args_list for msg in call.args[0]]
        self.assertEqual("".join(pieces), first.content + second.content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
