"""Offline catalog, SQL AST, engine sharing and audited-corpus regressions."""
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend" / "app"))
sys.path.insert(0, str(PROJECT / "audit"))
from service.database_catalog import ALLOWED_TABLES, DEMO_CORPUS_ID, catalog_payload
from service.database_explorer import DatabaseExplorer
from service.sql_safety import validate_select, bounded_select, read_only_connection
from service.text2sql_service import Text2SQLService
from configure_database_demo import prepare_rows, apply_rows, TAGGING_RULE


class SqlAstTests(unittest.TestCase):
    def test_common_analytics_quoted_identifiers_aliases_nested_and_union(self):
        queries = [
            'SELECT p."publication_year", COUNT(*) AS "文献数" FROM "public"."research_papers" AS p GROUP BY p."publication_year" ORDER BY p."publication_year"',
            "SELECT m.method_name, COUNT(DISTINCT p.paper_id) FROM research_papers p JOIN research_paper_methods m ON p.paper_id=m.paper_id GROUP BY m.method_name",
            "SELECT * FROM research_papers p WHERE p.paper_id IN (SELECT paper_id FROM research_paper_methods WHERE method_name='Transformer')",
            "SELECT title FROM research_papers UNION ALL SELECT policy_name FROM policy_data",
            "SELECT date_trunc('year', imported_at), extract(year FROM imported_at), to_char(imported_at,'YYYY') FROM research_papers",
            "SELECT CAST(publication_year AS TEXT), COALESCE(venue, '未知'), ROUND(AVG(publication_year), 2) FROM research_papers GROUP BY publication_year,venue",
            "SELECT CASE WHEN source_verified THEN '已核验' ELSE '未核验' END FROM research_papers",
            "SELECT publication_year, row_number() OVER (ORDER BY publication_year) FROM research_papers",
            "SELECT 'DELETE;--' AS literal, 1 AS value",
            "SELECT * FROM INDUSTRY_STATS",
        ]
        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(validate_select(query))

    def test_private_or_system_tables_rejected_at_every_depth(self):
        queries = [
            "SELECT * FROM users", 'SELECT * FROM "users"',
            "SELECT * FROM public.users u", "SELECT * FROM pg_catalog.pg_authid",
            "SELECT * FROM information_schema.tables", "SELECT * FROM private.research_papers",
            "SELECT * FROM anotherdb.public.research_papers", 'SELECT * FROM "RESEARCH_PAPERS"',
            "SELECT * FROM research_papers WHERE paper_id IN (SELECT id FROM memories)",
            "SELECT title FROM research_papers UNION SELECT password_hash FROM users",
            "SELECT * FROM (SELECT * FROM chat_sessions) p", "SELECT * FROM ONLY users",
        ]
        for query in queries:
            with self.subTest(query=query), self.assertRaises(ValueError):
                validate_select(query)

    def test_functions_casts_locks_comments_and_writes_rejected(self):
        queries = [
            "SELECT * FROM generate_series(1,1000000)", "SELECT * FROM unnest(ARRAY[1,2])",
            "SELECT pg_read_file('/etc/passwd')", "SELECT pg_catalog.pg_read_file('/etc/passwd')",
            "SELECT current_setting('password')", "SELECT query_to_xml('SELECT * FROM users',true,true,'')",
            "SELECT dblink('host=x','SELECT * FROM users')", "SELECT pg_sleep(10)",
            "SELECT CURRENT_USER", "SELECT 'users'::regclass", "SELECT 'x'::custom_type",
            "SELECT * FROM research_papers FOR UPDATE", "SELECT * INTO something FROM research_papers",
            "WITH p AS (SELECT * FROM users) SELECT * FROM p", "SELECT 1; SELECT 2",
            "SELECT 1 -- comment", "DELETE FROM research_papers", "SELECT /* x */ 1",
        ]
        for query in queries:
            with self.subTest(query=query), self.assertRaises(ValueError):
                validate_select(query)

    def test_all_table_references_are_qualified_and_result_bounded(self):
        result = bounded_select("SELECT * FROM research_papers WHERE paper_id IN (SELECT paper_id FROM research_paper_methods) LIMIT ALL", qualify_tables=True)
        self.assertIn("public.research_papers", result)
        self.assertIn("public.research_paper_methods", result)
        self.assertTrue(result.endswith("LIMIT :_result_limit"))

    def test_readonly_transaction_limits_and_safe_search_path(self):
        engine = Mock()
        engine.dialect.name = "postgresql"
        connection = engine.connect.return_value
        connection.execution_options.return_value = connection
        self.assertIs(read_only_connection(engine), connection)
        connection.execution_options.assert_called_once_with(postgresql_readonly=True)
        self.assertEqual([call.args[0] for call in connection.exec_driver_sql.call_args_list], [
            "SET LOCAL statement_timeout = '10000'", "SET LOCAL lock_timeout = '3000'",
            "SET LOCAL search_path = pg_catalog, public, pg_temp"])


class CatalogTests(unittest.TestCase):
    def test_catalog_filters_to_existing_published_tables_and_explains_scope(self):
        payload = catalog_payload(["research_papers", "research_paper_methods", "users", "memories"])
        self.assertEqual([table["name"] for table in payload["tables"]], ["research_papers", "research_paper_methods"])
        self.assertEqual(payload["default_table"], "research_papers")
        self.assertEqual(payload["corpus"]["expected_papers"], 120)
        self.assertIn("多标签", payload["notice"])
        self.assertIn("不代表", payload["notice"])

    def test_private_table_browse_and_schema_rejected_before_database_call(self):
        db = Mock()
        explorer = DatabaseExplorer(db)
        for name in ["users", "memories", "chat_sessions", 'research_papers";DROP TABLE users;--']:
            for method in [explorer.get_table_schema, explorer.get_table_data]:
                with self.subTest(name=name, method=method.__name__), self.assertRaises(ValueError):
                    method(name)
        db.execute.assert_not_called()

    def test_table_listing_query_enforces_server_catalog(self):
        db = Mock()
        db.execute.return_value = []
        self.assertEqual(DatabaseExplorer(db).get_tables(), [])
        statement, params = db.execute.call_args.args
        self.assertIn("table_name IN", str(statement))
        self.assertEqual(set(params["allowed_tables"]), ALLOWED_TABLES)

    def test_live_schema_only_published_tables_and_actual_columns(self):
        service = Text2SQLService.__new__(Text2SQLService)
        service.db_engine = Mock()
        inspector = Mock()
        inspector.get_table_names.return_value = ["research_papers", "users"]
        inspector.get_columns.return_value = [{"name": "paper_id", "type": "TEXT"}, {"name": "publication_year", "type": "INTEGER"}]
        inspector.get_pk_constraint.return_value = {"constrained_columns": ["paper_id"]}
        with patch("sqlalchemy.inspect", return_value=inspector):
            schema = service.get_live_schema()
        self.assertIn('public."research_papers"', schema)
        self.assertIn("publication_year", schema)
        self.assertNotIn("users", schema)
        inspector.get_columns.assert_called_once_with("research_papers", schema="public")

    def test_text2sql_route_uses_same_engine_and_qwen_plus(self):
        from router import database_router
        db = Mock()
        engine = db.get_bind.return_value
        with patch.object(database_router, "get_config", return_value=SimpleNamespace(api_key="test", base_url="https://example.invalid")), \
                patch.object(database_router, "Text2SQLService") as service:
            service.return_value.query = AsyncMock(return_value={"success": True, "data": [], "columns": []})
            asyncio.run(database_router.text2sql_query(database_router.Text2SQLRequest(question="按年统计"), Mock(), db))
        self.assertIs(service.call_args.kwargs["db_engine"], engine)
        self.assertEqual(service.call_args.kwargs["model"], "qwen-plus")
        self.assertNotIn("db_connection_string", service.call_args.kwargs)


class CorpusImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PROJECT / "audit" / "demo-result.json"
        cls.papers, cls.methods, cls.summary = prepare_rows(cls.source)

    def test_exact_audited_public_corpus_and_tags_without_invented_venue(self):
        self.assertEqual(len(self.papers), 120)
        self.assertEqual(len(self.methods), 188)
        self.assertEqual(Counter(p["evidence_level"] for p in self.papers), {"abstract": 114, "metadata": 6})
        self.assertTrue(all(p["venue"] is None for p in self.papers))
        self.assertTrue(all(p["source_verified"] and p["corpus_id"] == DEMO_CORPUS_ID for p in self.papers))
        self.assertEqual(len({(m["paper_id"], m["method_name"]) for m in self.methods}), 188)
        self.assertTrue(all(m["tagging_rule"] == TAGGING_RULE and json.loads(m["matched_keywords"]) for m in self.methods))
        self.assertEqual(self.summary["method_counts"]["Transformer"], 27)

    def test_repeat_preparation_is_identical_and_does_not_connect(self):
        with patch("sqlalchemy.create_engine", side_effect=AssertionError("no database")):
            self.assertEqual(prepare_rows(self.source), (self.papers, self.methods, self.summary))

    def test_tag_drift_aborts_instead_of_silently_changing_chart_meaning(self):
        data = json.loads(self.source.read_text(encoding="utf-8"))
        data["corpus_statistics"]["method_mentions"]["Transformer"] = 999
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "drift.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "方法统计"):
                prepare_rows(path)

    def test_unexpected_database_is_rejected_before_connection(self):
        engine = Mock()
        engine.dialect.name = "postgresql"
        engine.url.database = "another_project"
        with self.assertRaises(ValueError):
            apply_rows(engine, self.papers, self.methods)
        engine.begin.assert_not_called()

    def test_import_upserts_only_its_own_data_without_deletion(self):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        engine.url.database = "yayi_0929"
        connection = engine.begin.return_value.__enter__.return_value
        connection.execute.return_value.fetchall.return_value = []
        connection.execute.return_value.scalar_one.return_value = 120
        inspector = Mock()
        inspector.get_columns.side_effect = lambda table, schema: [{"name": name} for name in
            ((set(self.papers[0]) | {"imported_at"}) if table == "research_papers" else set(self.methods[0]))]
        with patch("sqlalchemy.inspect", return_value=inspector):
            for _ in range(2):
                self.assertEqual(apply_rows(engine, self.papers, self.methods), {"published_papers": 120})
        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        self.assertTrue(any("ON CONFLICT (paper_id) DO UPDATE" in sql and "WHERE research_papers.corpus_id = EXCLUDED.corpus_id" in sql for sql in statements))
        self.assertTrue(any("WHERE research_paper_methods.tagging_rule = EXCLUDED.tagging_rule" in sql for sql in statements))
        self.assertFalse(any(word in " ".join(statements).upper() for word in ("DELETE ", "TRUNCATE ", "DROP ")))

    def test_foreign_corpus_collision_aborts_before_upsert(self):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        engine.url.database = "yayi_0929"
        connection = engine.begin.return_value.__enter__.return_value
        connection.execute.return_value.fetchall.return_value = [("foreign-owned-paper",)]
        inspector = Mock()
        inspector.get_columns.side_effect = lambda table, schema: [{"name": name} for name in
            ((set(self.papers[0]) | {"imported_at"}) if table == "research_papers" else set(self.methods[0]))]
        with patch("sqlalchemy.inspect", return_value=inspector), self.assertRaisesRegex(ValueError, "其他语料"):
            apply_rows(engine, self.papers, self.methods)
        self.assertFalse(any("INSERT INTO" in str(call.args[0]) for call in connection.execute.call_args_list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
