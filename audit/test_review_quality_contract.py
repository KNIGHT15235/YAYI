"""Adversarial review-contract fixtures; no provider calls or quality metrics.

These tests distinguish acquired readable material, citation precision, and
semantic support. A real text payload must neither become automatically true
nor be discarded merely because its citation is only chunk-grained.
"""
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

from test_science_engine import agent, fixture_state, paper
from service.deep_research_v2.evidence import normalize_paragraph, register_evidence
from service.deep_research_v2.science_roles import evidence_input, review_science
from service.deep_research_v2.manual_review import initialize_manual_review
from service.deep_research_v2.review_quality import (
    build_review_materials, scope_overreach, validate_review_response,
)

ROLE = "service.deep_research_v2.science_roles"


def evidence_row(evidence_id="ev_one", text="The experiment did not find a significant improvement.", **changes):
    row = {"evidence_id": evidence_id, "title": "Acquired fixture abstract", "year": 2025,
           "evidence_level": "abstract", "text": text, "text_truncated": False,
           "locator": {"page": 1}, "locators": [{"page": 1}], "assets": [],
           "assets_omitted_for_budget": 0, "quote_candidates": [
               {"quote_id": "quote_fixture", "quote": text, "text_span": {"start": 0, "end": len(text)}}]}
    row.update(changes)
    return row


def claim_row(claim_id="claim_one", text="作者报告该实验未观察到显著提升。", ids=None):
    return {"claim_id": claim_id, "claim_text": text,
            "evidence_ids": ["ev_one"] if ids is None else ids,
            "evidence_links": [{"evidence_id": "ev_one", "verification": "chunk_only", "precision": "chunk"}]}


def result_row(claim, status="supported", relation="supports", reason_code="content_checked", **changes):
    row = {"claim_id": claim["claim_id"], "status": status,
           "reason": "The cited material explicitly describes the stated experiment; scope is unchanged.",
           "reason_code": reason_code,
           "evidence_checks": [{"evidence_id": eid, "relation": relation,
                                "reason": "Checked the supplied original material, not citation precision."}
                               for eid in claim["evidence_ids"]]}
    row.update(changes)
    return row


class ReviewQualityContractTests(unittest.TestCase):
    def test_chunk_only_does_not_remove_readable_original_material(self):
        claim = claim_row()
        materials = build_review_materials([evidence_row()])
        serialized = json.dumps(materials, ensure_ascii=False)
        self.assertIn("significant improvement", serialized)
        for metadata in ("quote_candidates", "quote_fixture", "locator", "evidence_links", "chunk_only"):
            self.assertNotIn(metadata, serialized)
        accepted, violations = validate_review_response({"results": [result_row(claim)]}, [claim], materials)
        self.assertFalse(violations)
        self.assertEqual(accepted[0]["status"], "supported")

    def test_readable_text_does_not_upgrade_semantic_insufficiency(self):
        claim = claim_row(text="该模型将召回率提高20个百分点。")
        materials = build_review_materials([evidence_row()])
        accepted, violations = validate_review_response({"results": [
            result_row(claim, status="insufficient", relation="insufficient")
        ]}, [claim], materials)
        self.assertFalse(violations)
        self.assertEqual(accepted[0]["status"], "insufficient")

    def test_readable_text_misreported_unreadable_is_contract_failure(self):
        claim = claim_row()
        materials = build_review_materials([evidence_row()])
        accepted, violations = validate_review_response({"results": [
            result_row(claim, status="unverified", relation="unreadable", reason_code="content_unavailable")
        ]}, [claim], materials)
        self.assertIn(claim["claim_id"], violations)
        self.assertFalse(any(row["status"] == "supported" for row in accepted))

    def test_metadata_without_original_content_cannot_be_supported(self):
        claim = claim_row()
        materials = build_review_materials([evidence_row(text="", evidence_level="metadata", quote_candidates=[])])
        accepted, violations = validate_review_response({"results": [result_row(claim)]}, [claim], materials)
        self.assertIn(claim["claim_id"], violations)
        self.assertFalse(any(row["status"] == "supported" for row in accepted))

    def test_duplicate_claim_results_are_not_silently_last_write_wins(self):
        claim = claim_row()
        duplicate = result_row(claim, status="insufficient", relation="insufficient")
        accepted, violations = validate_review_response({"results": [result_row(claim), duplicate]},
                                                        [claim], build_review_materials([evidence_row()]))
        self.assertIn(claim["claim_id"], violations)
        self.assertFalse(any(row["status"] == "supported" for row in accepted))

    def test_missing_or_foreign_claim_result_never_substitutes_for_expected_claim(self):
        claim = claim_row()
        foreign = result_row(claim_row("claim_foreign"))
        for rows in ([], [foreign], [{**foreign, "claim_id": ["malformed", "id"]}]):
            with self.subTest(rows=rows):
                accepted, violations = validate_review_response({"results": rows}, [claim],
                                                                build_review_materials([evidence_row()]))
                self.assertIn(claim["claim_id"], violations)
                self.assertFalse(any(row["status"] == "supported" for row in accepted))

    def test_each_cited_evidence_is_checked_and_foreign_checks_rejected(self):
        claim = claim_row(ids=["ev_one", "ev_two"])
        materials = build_review_materials([evidence_row(), evidence_row("ev_two")])
        valid = result_row(claim)
        for checks in (valid["evidence_checks"][:1], valid["evidence_checks"] + [
            {"evidence_id": "ev_forged", "relation": "supports", "reason": "Not supplied to reviewer."}
        ]):
            with self.subTest(checks=checks):
                accepted, violations = validate_review_response({"results": [
                    {**valid, "evidence_checks": checks}]}, [claim], materials)
                self.assertIn(claim["claim_id"], violations)
                self.assertFalse(any(row["status"] == "supported" for row in accepted))

    def test_supported_requires_direct_support_not_only_topic_relevance(self):
        claim = claim_row()
        accepted, violations = validate_review_response({"results": [
            result_row(claim, relation="insufficient")
        ]}, [claim], build_review_materials([evidence_row()]))
        self.assertIn(claim["claim_id"], violations)
        self.assertFalse(any(row["status"] == "supported" for row in accepted))

    def test_conflicting_evidence_cannot_coexist_with_supported_verdict(self):
        claim = claim_row(ids=["ev_one", "ev_two"])
        materials = build_review_materials([evidence_row(), evidence_row("ev_two")])
        conflicting = result_row(claim)
        conflicting["evidence_checks"][1]["relation"] = "contradicts"
        conflicting["evidence_checks"][1]["reason"] = "The second supplied source directly conflicts with the claim."
        accepted, violations = validate_review_response({"results": [conflicting]}, [claim], materials)
        self.assertFalse(accepted)
        self.assertIn("supported_with_conflicting_evidence", violations[claim["claim_id"]])
        # An explicit incomplete/conflicting assessment remains a completed
        # semantic result; the contract must not force a positive conclusion.
        accepted, violations = validate_review_response({"results": [
            {**conflicting, "status": "insufficient", "reason": "The sources conflict; no supported conclusion is available."}
        ]}, [claim], materials)
        self.assertFalse(violations)
        self.assertEqual(accepted[0]["status"], "insufficient")

    def test_malformed_json_field_types_are_rejected_without_raising(self):
        claim = claim_row()
        original = result_row(claim)
        invalid_rows = [
            {**original, "status": ["supported"]},
            {**original, "status": {"value": "supported"}},
            {**original, "reason_code": ["content_checked"]},
            {**original, "reason": {"text": "Not a reason string"}},
            {**original, "evidence_checks": [{**original["evidence_checks"][0], "evidence_id": ["ev_one"]}]},
            {**original, "evidence_checks": [{**original["evidence_checks"][0], "evidence_id": {"id": "ev_one"}}]},
            {**original, "evidence_checks": [{**original["evidence_checks"][0], "relation": ["supports"]}]},
            {**original, "evidence_checks": [{**original["evidence_checks"][0], "quote": ["copied"]}]},
        ]
        for row in invalid_rows:
            with self.subTest(row=row):
                accepted, violations = validate_review_response({"results": [row]}, [claim],
                                                                build_review_materials([evidence_row()]))
                self.assertIn(claim["claim_id"], violations)
                self.assertFalse(accepted)

    def test_exact_quote_from_metadata_does_not_establish_original_content_support(self):
        claim = claim_row(text="该方法已证明提升召回率。")
        text = "Title and catalogue metadata, not an acquired abstract."
        materials = build_review_materials([evidence_row(text=text, evidence_level="metadata")])
        row = result_row(claim)
        row["evidence_checks"][0]["quote"] = text
        accepted, violations = validate_review_response({"results": [row]}, [claim], materials)
        self.assertIn(claim["claim_id"], violations)
        self.assertFalse(accepted)

    def test_truncation_partial_asset_and_unread_pixels_remain_explicit(self):
        assets = [{"asset_id": "asset_table", "type": "table", "content": "Visible row: A | 64",
                   "content_truncated": True, "hydration": {"status": "partial", "omitted_row_records": 99}},
                  {"asset_id": "asset_image", "type": "image", "content": "Figure 1. Recall curves.",
                   "hydration": {"status": "visual_unverified", "visual_verification": "visual_unverified"}}]
        materials = build_review_materials([evidence_row(text="Only the supplied prefix is readable.",
                                                       text_truncated=True, assets=assets,
                                                       assets_omitted_for_budget=3)])
        serialized = json.dumps(materials, ensure_ascii=False)
        self.assertIn("partial", serialized)
        self.assertIn("visual_unverified", serialized)
        self.assertIn("Visible row", serialized)
        self.assertIn("Recall curves", serialized)
        self.assertTrue(any(key in serialized for key in ("text_truncated", "truncated")))
        claim = claim_row(text="原文提供了召回曲线的图注，图内数值尚未核验。")
        accepted, violations = validate_review_response({"results": [
            result_row(claim, status="insufficient", relation="insufficient")
        ]}, [claim], materials)
        self.assertFalse(violations)
        self.assertEqual(accepted[0]["status"], "insufficient")

    def test_asset_only_table_content_uses_real_hydration_response_shape(self):
        asset = {"asset_id": "asset_table", "type": "table", "content": "Visible original row: A | 64",
                 "content_truncated": True, "hydration": {"status": "partial", "omitted_row_records": 99}}
        materials = build_review_materials([evidence_row(text="", assets=[asset], quote_candidates=[])])
        self.assertTrue(materials[0]["availability"]["content_available"])
        self.assertFalse(materials[0]["availability"]["text_available"])
        self.assertEqual(materials[0]["availability"]["readable_asset_ids"], ["asset_table"])
        claim = claim_row(text="已展开表格中A行的数值为64，其他行尚未读取。")
        reviewed = result_row(claim)
        reviewed["evidence_checks"][0]["quote"] = "A | 64"
        accepted, violations = validate_review_response({"results": [reviewed]}, [claim], materials)
        self.assertFalse(violations)
        self.assertEqual(accepted[0]["status"], "supported")

    def test_image_caption_does_not_establish_unread_pixel_values(self):
        asset = {"asset_id": "asset_image", "type": "image", "content": "Figure 1. Recall curves.",
                 "hydration": {"status": "visual_unverified", "visual_verification": "visual_unverified"}}
        materials = build_review_materials([evidence_row(text="", assets=[asset], quote_candidates=[])])
        self.assertFalse(materials[0]["availability"]["visual_content_verified"])
        claim = claim_row(text="图中曲线显示Recall@20达到91%。")
        accepted, violations = validate_review_response({"results": [result_row(claim)]}, [claim], materials)
        self.assertIn(claim["claim_id"], violations)
        self.assertFalse(any(row["status"] == "supported" for row in accepted))

    def test_domain_absence_and_bounded_uncertainty_are_not_equivalent(self):
        for text in ("2024–2025年biomedical retrieval领域尚无同口径Recall@20对比研究。",
                     "所有真实研究均未提供可比的实验结果，因此该领域不存在直接证据。",
                     "本次检索未发现可比研究，因此整个领域不存在可比研究。",
                     "当前证据库没有可比研究，这说明所有真实研究均未提供可比实验。"):
            with self.subTest(text=text):
                self.assertTrue(scope_overreach(text))
        for text in ("本次检索的摘要中未找到同口径Recall@20对比，不能据此推断领域不存在。",
                     "当前证据库不足以核实该结论，仍保留为未知。",
                     "作者报告该实验未观察到显著提升。",
                     "该实验的结果并不支持提升20%的结论。"):
            with self.subTest(text=text):
                self.assertFalse(scope_overreach(text))
        claim = claim_row(text="该领域不存在可比研究。")
        accepted, violations = validate_review_response({"results": [result_row(claim)]}, [claim],
                                                        build_review_materials([evidence_row()]))
        self.assertFalse(violations)  # It is an explicit semantic/scope veto, not malformed JSON.
        self.assertEqual(accepted[0]["status"], "insufficient")
        self.assertIn("scope", json.dumps(accepted[0], ensure_ascii=False))


class BoundedReviewRetryTests(unittest.IsolatedAsyncioTestCase):
    def make_state(self):
        state = fixture_state(1)
        row = register_evidence(state, paper(0, abstract=(
            "The experiment did not find a significant improvement. " * 4)))
        claim = normalize_paragraph(state, "作者报告该实验未观察到显著提升。", [row["evidence_id"]], "sec_1", 0)
        state.update(claims=[claim], science_sections=[{"id": "sec_1", "title": "实验结果"}],
                     iteration=3, max_iterations=3)
        return state, claim

    async def test_retry_only_contains_invalid_claim_and_retains_valid_semantic_failure(self):
        state, valid_claim = self.make_state()
        valid_eid = valid_claim["evidence_ids"][0]
        other = register_evidence(state, paper(1, abstract=(
            "A separate experiment remains inconclusive under its reported setup. " * 4)))
        retry_eid = other["evidence_id"]
        self.assertNotEqual(valid_eid, retry_eid)
        invalid_claim = normalize_paragraph(state, "作者报告另一设置仍需核实。", [retry_eid], "sec_1", 1)
        state["claims"].append(invalid_claim)
        first = {"results": [result_row(valid_claim, status="insufficient", relation="insufficient"),
                             result_row(invalid_claim, status="unverified", relation="unreadable",
                                        reason_code="content_unavailable")]}
        corrected = {"results": [result_row(invalid_claim, status="insufficient", relation="insufficient")]}
        with patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=[first, corrected]) as model, \
             patch(ROLE + ".review_search_tasks", new_callable=AsyncMock, return_value=[]):
            await review_science(agent(), state)
        self.assertEqual(model.await_count, 2)
        retry_prompt = model.await_args_list[1].args[1]
        self.assertIn(invalid_claim["claim_id"], retry_prompt)
        self.assertNotIn(valid_claim["claim_id"], retry_prompt)
        self.assertNotIn(valid_eid, retry_prompt)
        retry_materials = json.loads(retry_prompt.rsplit("\n证据：", 1)[1])
        self.assertEqual([row["evidence_id"] for row in retry_materials], [retry_eid])
        self.assertEqual(valid_claim["verification_status"], "insufficient")
        self.assertEqual(invalid_claim["verification_status"], "insufficient")

    async def test_manual_problem_and_original_survive_target_retry_without_fake_quality_pass(self):
        state, target = self.make_state()
        eid = target["evidence_ids"][0]
        automatic = normalize_paragraph(state, "其他自动问题仍需直接证据。", [eid], "sec_1", 1)
        state["claims"].append(automatic)
        original = target["claim_text"]
        notes = "只保留该实验未观察到显著提升；不要额外声称召回率提高20%。"
        manual = {"notes": notes, "claim_ids": [target["claim_id"]],
                  "requested_at": "2026-10-15T01:00:00+00:00", "applied": False}
        state["manual_review_request"] = manual
        initialize_manual_review(state, manual, new_request=True)
        # A substantive edit has happened, but the explicit manual issue remains.
        target["claim_text"] = "该实验没有显著提升，但召回率仍提高20%。"
        target["verification_status"] = "pending"
        initial = {"results": [
            result_row(target, status="unverified", relation="unreadable", reason_code="content_unavailable"),
            result_row(automatic, status="insufficient", relation="insufficient"),
        ]}
        corrected = result_row(target, status="insufficient", relation="insufficient",
                               reason="正文虽然变化，仍保留原文未支持的20%结果，未解决人工指出的问题。")
        with patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=[
            initial, {"results": [corrected]}]) as model, \
             patch(ROLE + ".review_search_tasks", new_callable=AsyncMock, return_value=[]):
            await review_science(agent(), state)
        self.assertEqual(model.await_count, 2)
        for call in model.await_args_list:
            self.assertIn(notes, call.args[1])
            self.assertIn(original, call.args[1])
        retry_prompt = model.await_args_list[1].args[1]
        self.assertIn(target["claim_id"], retry_prompt)
        self.assertNotIn(automatic["claim_id"], retry_prompt)
        self.assertEqual(manual["targets"][0]["baseline_text"], original)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["verification_status"], "insufficient")
        self.assertEqual(target["verification_status"], "insufficient")
        self.assertNotEqual(state["review_verdict"], "pass")
        self.assertEqual(state["research_outcome"], "completed_with_warnings")

    async def test_availability_contract_retried_once_without_coercing_supported(self):
        state, claim = self.make_state()
        unavailable = result_row(claim, status="unverified", relation="unreadable", reason_code="content_unavailable")
        corrected = result_row(claim, status="insufficient", relation="insufficient")
        with patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=[
            {"results": [unavailable]}, {"results": [corrected]}]) as model, \
             patch(ROLE + ".review_search_tasks", new_callable=AsyncMock, return_value=[]):
            await review_science(agent(), state)
        self.assertEqual(model.await_count, 2)
        self.assertEqual(claim["verification_status"], "insufficient")
        self.assertNotEqual(state["review_verdict"], "pass")

    async def test_two_invalid_contracts_stop_unverified_and_preserve_claim_text(self):
        state, claim = self.make_state()
        original_text = claim["claim_text"]
        invalid = {"results": [result_row(claim, status="unverified", relation="unreadable",
                                         reason_code="content_unavailable")]}
        with patch(ROLE + ".json_call", new_callable=AsyncMock, side_effect=[
            copy.deepcopy(invalid), copy.deepcopy(invalid)]) as model, \
             patch(ROLE + ".review_search_tasks", new_callable=AsyncMock, return_value=[]):
            await review_science(agent(), state)
        self.assertEqual(model.await_count, 2)
        self.assertEqual(claim["verification_status"], "unverified")
        self.assertEqual(claim["claim_text"], original_text)
        self.assertEqual(state["quality_review_status"], "unconfirmed")
        self.assertNotEqual(state["review_verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
