"""Offline regressions for variable JSON shapes returned by industry Scout models."""
import copy
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from service.deep_research_v2.agents.scout import DeepScout, _normalize_extraction, _count_sources
from service.deep_research_v2.state import create_initial_state


URLS = ["https://example.com/report-a", "https://example.com/report-b"]


def state():
    result = create_initial_state("调研轨道交通信号系统产业链", "shape-test", search_web=True)
    result.update(phase="researching", outline=[{"id": "sec_1", "title": "产业链", "status": "pending",
                                               "search_queries": ["轨道交通信号系统产业链"]}])
    return result


def scout():
    result = DeepScout.__new__(DeepScout)
    result.name, result.logger, result.add_message = "ScoutShapeTest", logging.getLogger("shape-test"), Mock()
    result.fact_fingerprints = {}
    result._fetch_stock_data_if_relevant = AsyncMock()
    result._enrich_with_originals = AsyncMock()
    result._execute_search = AsyncMock(return_value=[{"title": "公开报告", "url": URLS[0], "summary": "检索摘要", "site_name": "来源"}])
    result._execute_local_search = AsyncMock(return_value=[])
    return result


def extraction():
    return {"extracted_facts": [{"content": "轨道交通信号系统包含车载设备与地面控制设备。",
                                "source_url": URLS, "source_name": ["来源甲", "来源乙"],
                                "credibility_score": .8,
                                "data_points": [{"name": "样本数", "value": 12, "unit": "个"}]}],
            "entities_discovered": [{"name": ["车载设备"], "type": "product", "relations": ["连接地面设备"]}],
            "key_insights": [], "source_tracing_queries": [], "follow_up_queries": []}


class ShapeNormalizationTests(unittest.TestCase):
    def test_normal_scalar_url_and_measured_value_are_unchanged(self):
        raw = extraction()
        raw["extracted_facts"][0]["source_url"] = URLS[0]
        normalized = _normalize_extraction(raw)["extracted_facts"][0]
        self.assertEqual(normalized["source_url"], URLS[0])
        self.assertEqual(normalized["data_points"][0]["value"], 12)
        self.assertEqual(raw["extracted_facts"][0]["source_url"], URLS[0])

    def test_multi_source_fact_has_one_real_primary_url_and_preserves_all_sources(self):
        normalized = _normalize_extraction(extraction())["extracted_facts"][0]
        self.assertEqual(normalized["source_url"], URLS[0])
        self.assertEqual(normalized["source_urls"], URLS)
        self.assertEqual(_count_sources([normalized, normalized]), 2)
        self.assertEqual(_count_sources(extraction()["extracted_facts"]), 2)

    def test_structured_numeric_values_are_skipped_without_inventing_numbers(self):
        normalized = _normalize_extraction({"extracted_facts": [None, "invalid", {"content": ["事实一", "事实二"],
            "source_url": [{"url": URLS[0]}, None], "data_points": [{"value": [10, 20]}, {"value": {"low": 10}}, {"value": 12}]}],
            "data_points": "invalid"})
        self.assertEqual(len(normalized["extracted_facts"]), 1)
        self.assertEqual(normalized["extracted_facts"][0]["content"], "事实一\n事实二")
        self.assertEqual(normalized["extracted_facts"][0]["source_url"], URLS[0])
        self.assertEqual(normalized["extracted_facts"][0]["data_points"], [{"value": 12}])
        self.assertEqual(normalized["data_points"], [])
        self.assertEqual(_normalize_extraction(["invalid top-level"]), {})

    def test_graph_handles_list_names_without_hashing_lists_or_merging_entities(self):
        st = state()
        st["knowledge_graph"] = {"nodes": [{"id": "existing", "name": ["车载设备"]}], "edges": []}
        scout()._update_knowledge_graph(st, [{"name": ["车载设备"]}, {"name": ["地面设备"], "relations": "通信"},
                                            {"name": ["多个", "不同实体"]}, None])
        self.assertEqual([node["name"] for node in st["knowledge_graph"]["nodes"]], ["车载设备", "地面设备"])
        self.assertEqual(st["knowledge_graph"]["edges"][0]["relation"], "通信")


class ScoutPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_search_completes_with_list_source_url(self):
        st, worker = state(), scout()
        worker._analyze_search_results = AsyncMock(return_value=extraction())
        await worker.process(st)
        self.assertEqual(st["facts"][0]["source_url"], URLS[0])
        self.assertEqual(st["facts"][0]["source_urls"], URLS)
        self.assertEqual(st["outline"][0]["status"], "researching")
        completed = [c.args[2] for c in worker.add_message.call_args_list
                     if c.args[1] == "research_step" and c.args[2].get("status") == "completed"]
        self.assertEqual(completed[-1]["stats"]["sources_count"], 2)

    async def test_recursive_search_normalizes_same_source_shape(self):
        st, worker = state(), scout()
        worker._analyze_deep_search_results = AsyncMock(return_value=extraction())
        await worker._execute_deep_search(st, "sec_1", ["原始资料"], "source_tracing", [], depth=2, max_depth=2)
        self.assertEqual(st["facts"][0]["source_url"], URLS[0])
        self.assertEqual(st["facts"][0]["source_urls"], URLS)
        self.assertEqual(st["facts"][0]["search_depth"], 2)
        worker._execute_search.assert_awaited_once_with("原始资料", count=6)

    async def test_supplement_completes_with_multi_source_fact(self):
        st, worker = state(), scout()
        st.update(phase="re_researching", pending_search_queries=["补充公开资料"])
        worker._analyze_supplementary_results = AsyncMock(return_value=extraction())
        await worker.process(st)
        self.assertEqual(st["phase"], "writing")
        self.assertEqual(st["facts"][0]["source_url"], URLS[0])
        self.assertEqual(st["facts"][0]["source_urls"], URLS)
        self.assertEqual(st["pending_search_queries"], [])

    async def test_resume_normalizes_saved_facts_without_repeating_completed_sections(self):
        st, worker = state(), scout()
        st["facts"] = copy.deepcopy(extraction()["extracted_facts"])
        st["outline"][0]["status"] = "researching"
        worker._research_section = AsyncMock()
        await worker.process(st)
        worker._research_section.assert_not_awaited()
        worker._execute_search.assert_not_awaited()
        self.assertEqual(st["facts"][0]["source_url"], URLS[0])
        self.assertEqual(st["facts"][0]["source_urls"], URLS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
