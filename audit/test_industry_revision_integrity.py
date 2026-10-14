"""Industry revisions must receive and preserve the complete report structure."""
import json
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from service.deep_research_v2.agents.writer import LeadWriter
from service.deep_research_v2.state import create_initial_state


def report():
    paragraphs = "这是来源明确的行业分析，适用范围以公开材料为限。\n\n" * 90
    return "# 行业背景研究\n\n" + "\n\n".join(
        f"## {i} 研究章节{i}\n\n### {i}.1 证据与分析\n\n{paragraphs}" for i in range(1, 7)
    ) + "\n\n## 结论与局限\n\nTAIL_CONCLUSION：本文不作市场规模预测。\n\n## 参考文献\n\n[公开报告](https://example.com/tail-source)"


def writer(result):
    worker = LeadWriter.__new__(LeadWriter)
    worker.name, worker.logger, worker.add_message = "RevisionTest", logging.getLogger("revision-test"), Mock()
    worker.call_llm = AsyncMock(return_value=json.dumps(result, ensure_ascii=False))
    worker.parse_json_response = json.loads
    return worker


def state(original):
    st = create_initial_state("行业背景调研", "revision-integrity")
    st.update(phase="revising", final_report=original,
              critic_feedback=[{"id": "issue_1", "severity": "major", "description": "收窄不受证据支持的判断",
                                "suggestion": "明确资料边界", "resolved": False}])
    return st


class RevisionIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_long_draft_and_tail_reach_the_revision_model(self):
        original = report()
        self.assertGreater(len(original), 10000)
        worker = writer({"revised_content": original, "changes_made": []})
        await worker._revise_report(state(original))
        prompt = worker.call_llm.call_args.kwargs["user_prompt"]
        self.assertIn(original, prompt)
        self.assertIn("TAIL_CONCLUSION", prompt)
        self.assertIn("https://example.com/tail-source", prompt)
        self.assertEqual(worker.call_llm.call_args.kwargs["max_tokens"], 16000)

    async def test_truncated_revision_cannot_replace_full_draft_or_resolve_issues(self):
        original = report()
        st = state(original)
        worker = writer({"revised_content": original[:6000], "addressed_issues": ["issue_1"],
                         "changes_made": ["声称已经完成修订"]})
        await worker._revise_report(st)
        self.assertEqual(st["final_report"], original)
        self.assertFalse(st["critic_feedback"][0]["resolved"])
        self.assertEqual(st["revision_integrity"]["status"], "rejected")
        self.assertIn("结论与局限", st["revision_integrity"]["missing_headings"])
        self.assertIn("参考文献", st["revision_integrity"]["missing_headings"])
        self.assertEqual(st["phase"], "reviewing")
        self.assertTrue(any(call.args[1] == "warning" for call in worker.add_message.call_args_list))
        self.assertFalse(any(call.args[1] == "revision_complete" for call in worker.add_message.call_args_list))

    async def test_targeted_complete_revision_is_accepted_with_tail_intact(self):
        original = report()
        revised = original.replace("这是来源明确的行业分析", "作者依据公开资料进行行业分析", 1)
        st = state(original)
        worker = writer({"revised_content": revised, "addressed_issues": ["issue_1"], "changes_made": ["收窄表述"]})
        await worker._revise_report(st)
        self.assertEqual(st["final_report"], revised)
        self.assertTrue(st["critic_feedback"][0]["resolved"])
        self.assertEqual(st["revision_integrity"]["status"], "accepted")
        self.assertIn("TAIL_CONCLUSION", st["final_report"])
        self.assertEqual(st["phase"], "reviewing")

    async def test_non_text_revision_does_not_destroy_original(self):
        original = report()
        st = state(original)
        await writer({"revised_content": ["partial fragment"], "addressed_issues": ["issue_1"]})._revise_report(st)
        self.assertEqual(st["final_report"], original)
        self.assertFalse(st["critic_feedback"][0]["resolved"])
        self.assertEqual(st["phase"], "reviewing")

    async def test_science_dispatch_and_initial_industry_writing_are_unchanged(self):
        worker = writer({})
        science = state(report())
        science["research_profile"] = {"mode": "science"}
        with patch("service.deep_research_v2.science_roles.write_science", new_callable=AsyncMock, return_value=science) as scientific:
            await worker.process(science)
        scientific.assert_awaited_once_with(worker, science)
        worker.call_llm.assert_not_awaited()
        industry = state(report())
        industry["phase"] = "writing"
        worker._write_report = AsyncMock(return_value=industry)
        await worker.process(industry)
        worker._write_report.assert_awaited_once_with(industry)
        worker.call_llm.assert_not_awaited()

    def test_code_example_headings_are_not_treated_as_report_sections(self):
        original = "# 报告\n\n## 正文\n```markdown\n## 示例标题\n```\n## 结论\n完成。"
        revised = original.replace("## 示例标题", "## 更正后的示例")
        self.assertEqual(LeadWriter._missing_revision_headings(original, revised), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
