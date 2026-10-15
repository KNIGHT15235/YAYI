"""Behavioral regressions for newly aligned knowledge and document features."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend' / 'app'))
from service import retrieval_service, embedding_service
from service.response_cache import RedisJSONCache
from service.text2sql_service import Text2SQLService
from router import knowledge_router, attachment_router


class AlignmentKnowledgeTests(unittest.TestCase):
    def test_rerank_preserves_cosine_and_moves_the_right_content(self):
        chunks = [{'id': 'a', 'content': 'irrelevant', 'score': .9},
                  {'id': 'b', 'content': 'answer', 'score': .8}]
        with patch.object(retrieval_service, 'generate_embedding', return_value=[[.1] * 1024]), \
             patch.object(retrieval_service, 'get_milvus_service') as milvus, \
             patch.object(retrieval_service, 'rerank_similarity', return_value=([.1, .99], None)):
            milvus.return_value.search.return_value = chunks
            milvus.return_value.search_keyword.return_value = []
            result = retrieval_service.search_chunks('kb_test', 'question')
            self.assertTrue(result['reranked'])
            self.assertEqual(result['results'][0]['id'], 'b')
            self.assertEqual(result['results'][0]['score'], .8)
            self.assertEqual(milvus.return_value.search.call_args.kwargs['top_k'], 50)

    def test_rerank_failure_is_visible_without_losing_results(self):
        with patch.object(retrieval_service, 'generate_embedding', return_value=[[.1] * 1024]), \
             patch.object(retrieval_service, 'get_milvus_service') as milvus, \
             patch.object(retrieval_service, 'rerank_similarity', side_effect=RuntimeError('quota')):
            milvus.return_value.search.return_value = [{'id': 'a', 'content': 'answer', 'score': .9}]
            milvus.return_value.search_keyword.return_value = []
            result = retrieval_service.search_chunks('kb_test', 'question')
            self.assertFalse(result['reranked'])
            self.assertTrue(result['warning'])
            self.assertEqual(len(result['results']), 1)

    def test_missing_vector_raises_instead_of_fake_empty_success(self):
        with patch.object(retrieval_service, 'generate_embedding', return_value=[None]):
            with self.assertRaises(ValueError):
                retrieval_service.search_chunks('kb_test', 'question')

    def test_provider_sorted_rerank_scores_are_restored_to_input_order(self):
        def reverse_nodes(nodes, query_str):
            nodes[0].score, nodes[1].score = .2, .8
            return list(reversed(nodes))
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'synthetic-audit-key'}), \
             patch.object(embedding_service, 'DashScopeRerank') as reranker:
            reranker.return_value.postprocess_nodes.side_effect = reverse_nodes
            scores, _ = embedding_service.rerank_similarity('question', ['a', 'b'])
            self.assertEqual(list(scores), [.2, .8])
            self.assertEqual(reranker.call_args.kwargs['model'], os.getenv('RERANK_MODEL', 'qwen3-rerank'))

    def test_embedding_cache_deduplicates_batches_and_accounts(self):
        cache = {}
        def get_value(_self, key):
            return cache.get(repr(key))
        def set_value(_self, key, value):
            cache[repr(key)] = value
        with patch.object(RedisJSONCache, 'get', get_value), patch.object(RedisJSONCache, 'set', set_value), \
             patch.object(embedding_service, 'OpenAI') as client:
            def complete(**kwargs):
                return Obj(data=[Obj(index=i, embedding=[float(i + 1)] * 3) for i in range(len(kwargs['input']))])
            client.return_value.embeddings.create.side_effect = complete
            first = embedding_service.generate_embedding(['same', 'same'], api_key='account-a', dimensions=3)
            second = embedding_service.generate_embedding('same', api_key='account-a', dimensions=3)
            self.assertEqual(first, [[1.] * 3, [1.] * 3])
            self.assertEqual(second, [1.] * 3)
            self.assertEqual(client.return_value.embeddings.create.call_count, 1)
            embedding_service.generate_embedding('same', api_key='account-b', dimensions=3)
            self.assertEqual(client.return_value.embeddings.create.call_count, 2)

    def test_cache_failure_does_not_prevent_underlying_request(self):
        import redis
        with patch('service.response_cache.redis.Redis') as cache:
            cache.return_value.get.side_effect = redis.ConnectionError('offline')
            cache.return_value.setex.side_effect = redis.ConnectionError('offline')
            storage = RedisJSONCache('audit', 30)
            self.assertIsNone(storage.get({'prompt': 'private'}))
            storage.set('key', {'value': 1})
            self.assertNotIn('private', storage.key({'prompt': 'private'}))

    def test_download_path_cannot_escape_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'store'
            root.mkdir()
            outside = Path(directory) / 'private.txt'
            outside.write_text('not downloadable')
            inside = root / 'original.txt'
            inside.write_text('downloadable')
            with patch.object(knowledge_router, 'UPLOAD_DIR', str(root)):
                self.assertIsNone(knowledge_router.stored_original(str(outside)))
                self.assertEqual(knowledge_router.stored_original(str(inside)), inside)

    def test_background_processing_retains_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original.txt'
            path.write_text('retained original')
            document = Obj(filename='original.txt')
            db = MagicMock()
            db.query.return_value.filter.return_value.first.return_value = document
            with patch('service.docmind_service.process_document_with_docmind',
                       return_value={'success': True, 'document_count': 1}):
                knowledge_router.process_document('id', str(path), 'kb', lambda: db)
            self.assertEqual(document.status, 'completed')
            self.assertTrue(path.exists())

    def test_ocr_attachment_stores_actual_text(self):
        attachment = Obj(filename='scan.png', status='pending')
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = attachment
        with patch.object(attachment_router, 'extract_with_docmind', return_value='Scanned audit 73'):
            attachment_router.process_attachment('id', 'scan.png', lambda: db)
        self.assertEqual(attachment.status, 'completed')
        self.assertEqual(attachment.content_text, 'Scanned audit 73')

    def test_docmind_failure_is_not_a_successful_attachment(self):
        attachment = Obj(filename='old.doc', status='pending')
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = attachment
        with patch.object(attachment_router, 'extract_with_docmind', side_effect=ValueError('service unavailable')):
            attachment_router.process_attachment('id', 'old.doc', lambda: db)
        self.assertEqual(attachment.status, 'failed')
        self.assertIn('unavailable', attachment.error_message)

    def test_live_schema_excludes_account_tables(self):
        service = Text2SQLService.__new__(Text2SQLService)
        service.db_engine = object()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ['company_data', 'users', 'long_term_memories']
        inspector.get_columns.return_value = [{'name': 'new_metric', 'type': 'INTEGER'}]
        inspector.get_pk_constraint.return_value = {'constrained_columns': []}
        with patch('sqlalchemy.inspect', return_value=inspector):
            schema = service.get_live_schema()
        self.assertIn('new_metric', schema)
        self.assertNotIn('users', schema)
        self.assertNotIn('long_term_memories', schema)

    def test_text2sql_disconnected_reports_error_without_calling_model(self):
        service = Text2SQLService.__new__(Text2SQLService)
        service.db_engine = None
        service.client = MagicMock()
        response = asyncio.run(service.generate_sql('count companies'))
        self.assertEqual(response['sql'], '')
        service.client.chat.completions.create.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
