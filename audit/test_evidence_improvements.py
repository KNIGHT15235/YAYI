"""Offline evidence-contract regressions; no provider calls or factuality claims."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from service.document_assets import enrich_chunks, hydrate_asset_response
from service.deep_research_v2.evidence import (
    register_evidence, research_sources, sync_sources, normalize_paragraph,
    render_claim, render_science_report, validate_citations, references_from_ledger, citation_numbers,
    evidence_quote_candidates,
)
from service.deep_research_v2.science_roles import evidence_input, revise_science
from service.deep_research_v2.manual_review import initialize_manual_review


def local_row(chunk="chunk1", **changes):
    row = {"document_id": "doc1", "knowledge_base_id": "kb1", "document_version": "v1",
           "chunk_id": chunk, "title": "Local methods paper", "url": "/knowledge-bases/kb1/documents/doc1/download",
           "content": "Method A is evaluated under the reported setup. " * 4,
           "locators": [{"page": 3, "equation_number": "4", "bbox": [1, 2, 3, 4]}], "verified": True}
    row.update(changes)
    return row


def table_asset(rows=30):
    data = [{"row_index": 0, "cells": ["Method", "Accuracy (%)"], "text": "Method | Accuracy (%)"}]
    data.extend({"row_index": index, "cells": [f"Method{index}", str(80 + index / 10)],
                 "text": f"Method{index} | {80 + index / 10}"} for index in range(1, rows))
    return SimpleNamespace(id="asset1", document_id="doc1", document_version="v1", asset_type="table",
                           content="Units: accuracy percent; same held-out split.\n" + "\n".join("|" + row["text"] + "|" for row in data),
                           locator={"page": 3, "table_number": "2", "table_rows": data},
                           media_type="application/json", content_hash="fixture", file_path=None)


class UnifiedSourceTests(unittest.TestCase):
    def test_local_chunks_and_web_sources_share_one_deduplicated_corpus(self):
        state = {}
        first = register_evidence(state, local_row(), local=True)
        second = register_evidence(state, local_row("chunk2", content="Different acquired text. " * 6), local=True)
        self.assertEqual(first["source_id"], second["source_id"])
        self.assertEqual(len(state["papers"]), 1)
        self.assertEqual(len(research_sources(state)[0]["evidence_ids"]), 2)
        web = register_evidence(state, {"title": "Public paper", "doi": "10.0000/test", "url": "https://example.invalid/paper",
                                       "abstract": "An acquired abstract. " * 8, "verified": True})
        self.assertEqual(len(state["papers"]), 2)
        register_evidence(state, {"title": "Public paper", "doi": "10.0000/test", "url": web["url"],
                                  "abstract": "An acquired abstract. " * 8, "verified": True})
        self.assertEqual(len(sync_sources(state)), 2)

    def test_full_local_identity_survives_registration(self):
        state = {}
        row = register_evidence(state, local_row(text_start=100, text_end=200, asset_ids=["asset1"]), local=True)
        for key, value in {"knowledge_base_id": "kb1", "document_version": "v1", "chunk_id": "chunk1",
                           "text_start": 100, "text_end": 200, "asset_ids": ["asset1"], "source_type": "local"}.items():
            self.assertEqual(row[key], value)

    def test_explicit_doi_joins_channels_without_discarding_document_versions(self):
        state = {}
        first = register_evidence(state, local_row(doi="https://doi.org/10.0000/SHARED"), local=True)
        second = register_evidence(state, local_row("chunk-v2", doi="10.0000/shared", document_version="v2"), local=True)
        web = register_evidence(state, {"title": "Different provider title", "doi": "10.0000/shared",
                                       "url": "https://example.invalid/shared", "abstract": "Public abstract. " * 20, "verified": True})
        self.assertEqual(len(state["evidence_ledger"]), 3)
        sources = sync_sources(state)
        self.assertEqual(len(sources), 1)
        self.assertEqual(set(sources[0]["evidence_ids"]), {first["evidence_id"], second["evidence_id"], web["evidence_id"]})
        self.assertEqual({v["document_version"] for v in sources[0]["document_versions"]}, {"v1", "v2"})
        self.assertEqual(set(sources[0]["source_types"]), {"local", "web"})
        self.assertEqual(len(references_from_ledger(state)), 1)
        self.assertEqual(citation_numbers(state)[first["source_id"]], citation_numbers(state)[web["source_id"]])
        self.assertEqual(len(sync_sources(state)), 1)  # A second sync must not re-add a representative.

    def test_identical_titles_do_not_merge_different_explicit_dois_or_local_documents(self):
        state = {}
        for index in range(2):
            register_evidence(state, {"title": "Same title", "doi": f"10.0000/{index}",
                                      "url": f"https://example.invalid/{index}", "verified": True})
            register_evidence(state, local_row(document_id=f"doc{index}", title="Same title"), local=True)
        self.assertEqual(len(research_sources(state)), 4)


class AssetHydrationTests(unittest.TestCase):
    def test_enrichment_uses_research_query_to_select_table_rows(self):
        asset = table_asset()
        record = SimpleNamespace(chunk_id="chunk1", document_id="doc1", document_version="v1",
                                 locators=[{"page": 3}], content_hash="fixture", text_start=0, text_end=20,
                                 asset_ids=["asset1"], document=SimpleNamespace(knowledge_base_id="kb1"))
        provenance_query, asset_query = MagicMock(), MagicMock()
        for query in (provenance_query, asset_query):
            for method in ("options", "join", "filter"):
                getattr(query, method).return_value = query
        provenance_query.all.return_value = [record]
        asset_query.all.return_value = [asset]
        db = MagicMock()
        # Reuse the same authorized chunk and table; only the real query changes.
        # No row locator or chunk text supplies a fallback for the desired row.
        for query_text, expected, excluded in (("Method20", 20, 5), ("Method5", 5, 20)):
            with self.subTest(query=query_text):
                db.query.side_effect = [provenance_query, asset_query]
                rows = enrich_chunks(db, "kb_fixture", [{"id": "chunk1", "content": "Results section."}],
                                     "kb1", hydrate=True, query=query_text)
                selected = {row["row_index"] for row in rows[0]["assets"][0]["locator"]["table_rows"]}
                self.assertTrue({0, expected - 1, expected, expected + 1}.issubset(selected))
                self.assertNotIn(excluded, selected)

    def test_table_hydration_keeps_header_selected_row_units_and_neighbours(self):
        hydrated = hydrate_asset_response(table_asset(), "kb1", query="Method20", max_chars=5000,
                                         locators=[{"page": 3, "row_index": 20}])
        indices = {row["row_index"] for row in hydrated["locator"]["table_rows"]}
        self.assertTrue({0, 19, 20, 21}.issubset(indices))
        self.assertIn("accuracy percent", hydrated["content"])
        self.assertIn("Accuracy (%)", hydrated["content"])
        self.assertEqual(hydrated["hydration"]["status"], "partial")
        self.assertGreater(hydrated["hydration"]["omitted_row_records"], 0)

    def test_cell_groups_keep_same_row_columns_together(self):
        asset = table_asset(2)
        asset.locator["table_rows"] = [{"row_start": 7, "column_start": 0, "text": "MethodX"},
                                         {"row_start": 7, "column_start": 1, "text": "92.4"}]
        hydrated = hydrate_asset_response(asset, "kb1", query="MethodX", max_chars=2000)
        self.assertEqual(len(hydrated["locator"]["table_rows"]), 2)
        self.assertIn("MethodX | 92.4", hydrated["content"])

    def test_budget_never_silently_claims_complete_table(self):
        hydrated = hydrate_asset_response(table_asset(), "kb1", max_chars=0)
        self.assertEqual(hydrated["content"], "")
        self.assertEqual(hydrated["locator"]["table_rows"], [])
        self.assertEqual(hydrated["hydration"]["status"], "unavailable")
        self.assertTrue(hydrated["content_truncated"])

    def test_image_caption_does_not_become_visual_verification(self):
        asset = table_asset()
        asset.asset_type, asset.content, asset.locator = "image", "Figure 2. Ablation results", {"page": 4, "figure_number": 2}
        hydrated = hydrate_asset_response(asset, "kb1")
        self.assertEqual(hydrated["hydration"]["visual_verification"], "visual_unverified")
        self.assertIn("未执行视觉核验", hydrated["hydration"]["reason"])


class ClaimLocatorTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        asset = hydrate_asset_response(table_asset(3), "kb1")
        self.evidence = register_evidence(self.state, local_row(assets=[asset]), local=True)
        self.eid = self.evidence["evidence_id"]

    def claim(self, links=None):
        return normalize_paragraph(self.state, "Method2 was evaluated.", [self.eid], "sec1", 0, evidence_links=links)

    def test_valid_asset_row_and_literal_quote_produce_claim_viewer_link(self):
        claim = self.claim([{"evidence_id": self.eid, "asset_id": "asset1",
                             "locator": {"page": 3, "table_number": "2", "row_index": 2}, "quote": "Method2 | 80.2"}])
        self.assertEqual(claim["evidence_link_errors"], [])
        self.assertEqual(claim["evidence_links"][0]["verification"], "validated")
        self.assertEqual(claim["evidence_links"][0]["knowledge_base_id"], "kb1")
        self.assertIn("#claim-evidence:", render_claim(self.state, claim))

    def test_coarse_old_calls_stay_compatible_without_claiming_exact_position(self):
        claim = self.claim()
        self.assertEqual(claim["citation_precision"], "chunk")
        self.assertEqual(claim["evidence_links"][0]["verification"], "chunk_only")
        original = copy.deepcopy(claim)
        rendered = render_claim(self.state, claim)
        self.assertIn("#claim-evidence:", rendered)
        self.assertNotIn("/knowledge-bases/", rendered)
        self.assertEqual(claim, original)  # Navigation must not upgrade provenance/quality.
        empty = self.claim([{"evidence_id": self.eid, "locator": {}}])
        self.assertEqual(empty["evidence_link_errors"], [])
        self.assertEqual(empty["citation_precision"], "chunk")

    def test_viewer_link_requires_exact_local_document_version_and_chunk_binding(self):
        for field in ("knowledge_base_id", "document_id", "document_version", "chunk_id"):
            with self.subTest(field=field):
                claim = self.claim()
                claim["evidence_links"][0][field] = "foreign"
                self.assertNotIn("#claim-evidence:", render_claim(self.state, claim))

    def test_web_citation_keeps_its_public_source_url(self):
        state = {}
        row = register_evidence(state, {"title": "Public source", "url": "https://example.invalid/paper",
                                        "abstract": "Acquired public abstract.", "verified": True})
        claim = normalize_paragraph(state, "Statement", [row["evidence_id"]], "sec1", 0)
        rendered = render_claim(state, claim)
        self.assertIn("https://example.invalid/paper", rendered)
        self.assertNotIn("#claim-evidence:", rendered)

    def test_unknown_asset_forged_row_quote_span_and_identity_are_rejected(self):
        cases = [{"asset_id": "foreign"}, {"locator": {"page": 999}},
                 {"quote": "a fact not in source"}, {"text_span": {"start": -1, "end": 8}},
                 {"knowledge_base_id": "other"}, {"asset_id": "asset1", "locator": {"row_index": 99}}]
        for case in cases:
            with self.subTest(case=case):
                claim = self.claim([{"evidence_id": self.eid, **case}])
                self.assertTrue(claim["evidence_link_errors"])
                self.assertEqual(claim["citation_precision"], "chunk")
                self.state["claims"] = [claim]
                self.assertEqual(validate_citations(self.state)[0]["status"], "insufficient")

    def test_locator_and_quote_must_revalidate_after_asset_version_changes(self):
        claim = self.claim([{"evidence_id": self.eid, "asset_id": "asset1", "quote": "Method2 | 80.2"}])
        self.state["claims"] = [claim]
        self.evidence["assets"][0]["document_version"] = "v2"
        self.assertEqual(validate_citations(self.state)[0]["status"], "insufficient")

    def test_real_quote_from_another_real_row_is_not_a_valid_support_pointer(self):
        claim = self.claim([{"evidence_id": self.eid, "asset_id": "asset1",
                             "locator": {"row_index": 2}, "quote": "Method1 | 80.1"}])
        self.assertTrue(claim["evidence_link_errors"])

    def test_retrieval_does_not_discard_previously_acquired_asset_quote(self):
        old_asset = self.evidence["assets"][0]
        old_asset["hydration"]["status"] = "partial"
        excerpt = old_asset["content"][:20]
        claim = self.claim([{"evidence_id": self.eid, "asset_id": "asset1", "quote": excerpt,
                             "text_span": {"start": 0, "end": len(excerpt)}}])
        new_asset = copy.deepcopy(old_asset)
        new_asset["content"] = "Another acquired source row."
        register_evidence(self.state, local_row(assets=[new_asset]), local=True)
        self.state["claims"] = [claim]
        self.assertFalse(validate_citations(self.state))

    def test_text_span_is_checked_against_exact_selected_content(self):
        text = self.evidence["content"]
        claim = self.claim([{"evidence_id": self.eid, "quote": text[:8], "text_span": {"start": 0, "end": 8}}])
        self.assertFalse(claim["evidence_link_errors"])
        claim = self.claim([{"evidence_id": self.eid, "quote": text[:8], "text_span": {"start": 1, "end": 9}}])
        self.assertTrue(claim["evidence_link_errors"])


class QuoteCandidateTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.row = register_evidence(self.state, local_row(
            content="Hybrid minus vector recall is 8.0percentage points, not 8 percent relative improvement.\n"
                    "ENGINEERING TEST FIXTURE- NOT A REAL RESEARCH PUBLICATION",
            text_start=100), local=True)
        self.eid = self.row["evidence_id"]

    def claim(self, raw):
        return normalize_paragraph(self.state, "Scoped statement", [self.eid], "s", 0,
                                   evidence_links=[{"evidence_id": self.eid, **raw}])

    def test_quote_id_resolves_exact_ocr_text_and_span_without_claiming_semantic_support(self):
        candidate = evidence_quote_candidates(self.row)[0]
        claim = self.claim({"quote_id": candidate["quote_id"]})
        link = claim["evidence_links"][0]
        self.assertFalse(claim["evidence_link_errors"])
        self.assertIn("8.0percentage", link["quote"])
        self.assertEqual(link["quote"], self.row["content"][link["text_span"]["start"]:link["text_span"]["end"]])
        self.assertEqual(link["document_text_span"]["start"], 100 + link["text_span"]["start"])
        self.assertEqual(claim["verification_status"], "pending")
        self.state["claims"] = [claim]
        self.assertFalse(validate_citations(self.state))

    def test_unknown_or_cross_evidence_candidate_is_rejected(self):
        other = register_evidence(self.state, local_row("other", content=self.row["content"]), local=True)
        foreign_id = evidence_quote_candidates(other)[0]["quote_id"]
        for identity in ("quote_unknown", foreign_id):
            claim = self.claim({"quote_id": identity})
            self.assertTrue(claim["evidence_link_errors"])
            self.assertEqual(claim["citation_precision"], "chunk")

    def test_candidate_cannot_override_forged_quote_asset_or_span(self):
        candidate = evidence_quote_candidates(self.row)[0]
        changes = [{"quote": candidate["quote"].replace("8.0", "9.0")},
                   {"quote": candidate["quote"].replace("not ", "")},
                   {"quote": candidate["quote"].replace("8.0percentage", "8.0 percentage")},
                   {"text_span": {"start": False, "end": candidate["text_span"]["end"]}},
                   {"asset_id": "foreign"}]
        dash = evidence_quote_candidates(self.row)[1]
        changes.append({"quote_id": dash["quote_id"], "quote": dash["quote"].replace("-", "—")})
        for change in changes:
            with self.subTest(change=change):
                claim = self.claim({"quote_id": candidate["quote_id"], **change})
                self.assertTrue(claim["evidence_link_errors"])

    def test_asset_candidates_require_authorized_hydration_and_keep_real_row_binding(self):
        asset = hydrate_asset_response(table_asset(3), "kb1")
        self.row["assets"] = [asset]
        self.assertFalse(any(row.get("asset_id") for row in evidence_quote_candidates(self.row)))
        self.row["asset_hydration"] = {"authorized_scope": True, "requested": True}
        candidate = next(row for row in evidence_quote_candidates(self.row)
                         if row.get("asset_id") == "asset1" and row["quote"] == "Method2 | 80.2")
        claim = self.claim({"quote_id": candidate["quote_id"], "locator": {"row_index": 2}})
        self.assertFalse(claim["evidence_link_errors"])
        self.assertEqual(claim["evidence_links"][0]["asset_id"], "asset1")
        wrong_row = self.claim({"quote_id": candidate["quote_id"], "locator": {"row_index": 1}})
        self.assertTrue(wrong_row["evidence_link_errors"])
        asset["hydration"]["status"] = "unavailable"
        self.assertTrue(self.claim({"quote_id": candidate["quote_id"]})["evidence_link_errors"])

    def test_candidate_revalidates_acquired_text_and_document_version(self):
        candidate = evidence_quote_candidates(self.row)[0]
        claim = self.claim({"quote_id": candidate["quote_id"]})
        self.state["claims"] = [claim]
        original = self.row["content"]
        self.row["content"] = original.replace("8.0", "9.0")
        self.assertTrue(validate_citations(self.state))
        self.row["content"] = original
        self.row["document_version"] = "another-version"
        self.assertTrue(validate_citations(self.state))

    def test_partial_asset_candidates_never_include_unexpanded_rows(self):
        asset = hydrate_asset_response(table_asset(30), "kb1", query="Method20", max_chars=5000)
        self.assertEqual(asset["hydration"]["status"], "partial")
        self.row.update(assets=[asset], asset_hydration={"authorized_scope": True, "requested": True})
        candidates = [row for row in evidence_quote_candidates(self.row) if row.get("asset_id")]
        self.assertTrue(any(row["quote"] == "Method20 | 82.0" for row in candidates))
        self.assertFalse(any("Method10 |" in row["quote"] for row in candidates))
        for row in candidates:
            self.assertEqual(row["quote"], asset["content"][row["text_span"]["start"]:row["text_span"]["end"]])

    def test_image_caption_candidate_does_not_upgrade_visual_verification(self):
        source = table_asset()
        source.asset_type, source.content = "image", "Figure 2. Method comparison caption only."
        source.locator = {"page": 3, "figure_number": 2}
        asset = hydrate_asset_response(source, "kb1")
        self.row.update(assets=[asset], asset_hydration={"authorized_scope": True, "requested": True})
        candidate = next(row for row in evidence_quote_candidates(self.row) if row.get("asset_id"))
        claim = self.claim({"quote_id": candidate["quote_id"]})
        self.assertFalse(claim["evidence_link_errors"])
        self.assertEqual(claim["evidence_links"][0]["visual_verification"], "visual_unverified")
        self.assertEqual(claim["verification_status"], "pending")

    def test_prompt_limits_filter_candidates_without_changing_their_ids(self):
        small = evidence_input(self.state, limit=90)[0]
        large = evidence_input(self.state, limit=500)[0]
        self.assertTrue(small["quote_candidates"])
        self.assertLess(len(small["quote_candidates"]), len(large["quote_candidates"]))
        by_id = {row["quote_id"]: row for row in large["quote_candidates"]}
        for row in small["quote_candidates"]:
            self.assertEqual(row, by_id[row["quote_id"]])
            self.assertLessEqual(row["text_span"]["end"], len(small["text"]))
        tiny = evidence_input(self.state, limit=500, max_content_chars=5)[0]
        self.assertEqual(tiny["quote_candidates"], [])

    def test_rejected_quote_diagnostics_are_bounded_and_legacy_quotes_remain_strict(self):
        invalid = "never acquired" * 1000
        claim = self.claim({"quote": invalid, "locator": {"page": 3}})
        detail = claim["evidence_link_errors"][0]["rejected"]
        self.assertEqual(detail["quote_chars"], len(invalid))
        self.assertEqual(len(detail["quote_preview"]), 280)
        self.assertTrue(detail["quote_truncated"])
        exact = self.row["content"].splitlines()[0]
        self.assertFalse(self.claim({"quote": exact})["evidence_link_errors"])
        self.assertTrue(self.claim({"quote": exact.replace("8.0percentage", "8.0 percentage")})["evidence_link_errors"])


class QuoteRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_target_mapping_is_separate_from_automatic_quote_repairs(self):
        state = {"query": "Scoped synthetic review", "phase": "revising", "errors": [],
                 "science_sections": [{"id": "s", "title": "Results"}], "draft_sections": {}}
        row = register_evidence(state, local_row(content="The sample contains a 2020 paper, not an origin claim."), local=True)
        target = normalize_paragraph(state, "This field began after 2020.", [row["evidence_id"]], "s", 0)
        other = normalize_paragraph(state, "An unrelated citation needs repair.", [row["evidence_id"]], "s", 1)
        target["verification_status"], other["verification_status"] = "supported", "insufficient"
        state["claims"] = [target, other]
        note = "收窄所选声明的年代范围，不能把样本年份当作起源。"
        state["manual_review_request"] = {"notes": note, "claim_ids": [target["claim_id"]], "applied": False}
        initialize_manual_review(state, state["manual_review_request"], new_request=True)
        candidate = evidence_quote_candidates(row)[0]
        # Both citations are repaired but the requested target body is unchanged.
        response = {"revisions": [{"claim_id": claim["claim_id"], "text": claim["claim_text"],
                    "evidence_ids": [row["evidence_id"]],
                    "evidence_links": [{"evidence_id": row["evidence_id"], "quote_id": candidate["quote_id"]}]}
                    for claim in state["claims"]]}
        original_target = target["claim_text"]
        agent = SimpleNamespace(add_message=lambda *args, **kwargs: None)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, return_value=response) as call:
            await revise_science(agent, state)
        prompt = call.call_args.args[1]
        request = json.loads(prompt.split("\n人工定向修订请求（JSON）：", 1)[1].split("\n人工指令适用规则：", 1)[0])
        self.assertEqual(request, {"scope": "selected_claims", "target_claim_ids": [target["claim_id"]],
                                  "targets": [{"claim_id": target["claim_id"], "original_text": original_target}],
                                  "review_notes": note})
        self.assertIn(other["claim_id"], prompt)
        self.assertIn("不在 targets 中的段落，仅按其各自的审核错误修复", prompt)
        self.assertIs(call.call_args.kwargs["use_cache"], False)
        self.assertFalse(state["manual_review_request"]["applied"])
        self.assertEqual(state["manual_review_request"]["hypothesis_review_status"], "not_requested")
        self.assertEqual(state["manual_review_request"]["changed_claim_ids"], [])
        self.assertEqual(state["manual_review_request"]["unchanged_requested_claim_ids"], [target["claim_id"]])
        self.assertEqual(set(state["manual_review_request"]["revised_claim_ids"]), {target["claim_id"], other["claim_id"]})
        self.assertEqual(target["verification_status"], "pending")
        self.assertEqual(state["phase"], "reviewing")

    async def test_selected_claim_edit_does_not_reopen_unrequested_hypotheses(self):
        state = {"query": "Scoped synthetic review", "phase": "revising", "errors": [],
                 "science_sections": [{"id": "s", "title": "Results"}], "draft_sections": {},
                 "iteration": 3, "max_iterations": 4, "review_verdict": "unconfirmed",
                 "quality_review_status": "unconfirmed"}
        row = register_evidence(state, local_row(), local=True)
        target = normalize_paragraph(state, "Overbroad claim.", [row["evidence_id"]], "s", 0)
        other = normalize_paragraph(state, "Unselected statement.", [row["evidence_id"]], "s", 1)
        target["verification_status"] = other["verification_status"] = "supported"
        state["claims"] = [target, other]
        state["hypotheses"] = [{"id": "hyp_1", "content": "Unrelated hypothesis", "status": "insufficient",
                                "reason": "Existing evidence limitation", "evidence_ids": [row["evidence_id"]]}]
        original_hypotheses, original_other = copy.deepcopy(state["hypotheses"]), copy.deepcopy(other)
        state["manual_review_request"] = {"notes": "Only narrow the selected statement.",
            "claim_ids": [target["claim_id"]], "applied": False, "hypothesis_review_status": "unconfirmed"}
        initialize_manual_review(state, state["manual_review_request"], new_request=True)
        response = {"revisions": [{"claim_id": target["claim_id"], "text": "A narrowed claim under the reported setup.",
                                   "evidence_ids": [row["evidence_id"]]}]}
        agent = SimpleNamespace(add_message=lambda *args, **kwargs: None)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, return_value=response) as call, \
             patch("service.deep_research_v2.science_roles.review_hypotheses_with_notes", new_callable=AsyncMock) as hypotheses:
            await revise_science(agent, state)
        self.assertEqual(call.await_count, 1)
        hypotheses.assert_not_awaited()
        self.assertEqual(state["hypotheses"], original_hypotheses)
        self.assertEqual(other, original_other)
        self.assertTrue(state["manual_review_request"]["applied"])
        self.assertEqual(state["manual_review_request"]["hypothesis_review_status"], "not_requested")
        self.assertEqual(state["manual_review_request"]["changed_claim_ids"], [target["claim_id"]])
        self.assertEqual(target["verification_status"], "pending")
        self.assertEqual(state["phase"], "reviewing")
        self.assertEqual(state["review_verdict"], "unconfirmed")
        self.assertEqual(state["quality_review_status"], "unconfirmed")
        self.assertEqual((state["iteration"], state["max_iterations"]), (3, 4))

    async def test_global_manual_edit_still_requires_requested_hypothesis_review(self):
        state = {"query": "Scoped synthetic review", "phase": "revising", "errors": [],
                 "science_sections": [{"id": "s", "title": "Results"}], "draft_sections": {}}
        row = register_evidence(state, local_row(), local=True)
        claim = normalize_paragraph(state, "Original statement.", [row["evidence_id"]], "s", 0)
        claim["verification_status"] = "supported"
        state["claims"] = [claim]
        state["hypotheses"] = [{"id": "hyp_1", "content": "Global hypothesis", "evidence_ids": [row["evidence_id"]]}]
        state["manual_review_request"] = {"notes": "Review the whole report and hypotheses.", "claim_ids": [], "applied": False}
        initialize_manual_review(state, state["manual_review_request"], new_request=True)
        response = {"revisions": [{"claim_id": claim["claim_id"], "text": "Revised statement.", "evidence_ids": [row["evidence_id"]]}]}
        agent = SimpleNamespace(add_message=lambda *args, **kwargs: None)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock,
                   side_effect=[response, {"hypotheses": []}]) as call:
            await revise_science(agent, state)
        self.assertEqual(call.await_count, 2)
        self.assertFalse(state["manual_review_request"]["applied"])
        self.assertEqual(state["manual_review_request"]["hypothesis_review_status"], "unconfirmed")
        self.assertEqual(state["manual_review_request"]["changed_claim_ids"], [claim["claim_id"]])
        self.assertEqual(claim["verification_status"], "pending")

    async def test_unscoped_manual_request_explicitly_maps_all_claims(self):
        state = {"query": "Scoped synthetic review", "phase": "revising", "errors": [],
                 "science_sections": [{"id": "s", "title": "Results"}], "draft_sections": {}}
        row = register_evidence(state, local_row(), local=True)
        state["claims"] = [normalize_paragraph(state, text, [row["evidence_id"]], "s", index)
                           for index, text in enumerate(("First paragraph.", "Second paragraph."))]
        for claim in state["claims"]:
            claim["verification_status"] = "supported"
        state["manual_review_request"] = {"notes": "逐段补充适用条件。", "claim_ids": [], "applied": False}
        initialize_manual_review(state, state["manual_review_request"], new_request=True)
        agent = SimpleNamespace(add_message=lambda *args, **kwargs: None)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock,
                   return_value={"revisions": []}) as call:
            await revise_science(agent, state)
        prompt = call.call_args.args[1]
        request = json.loads(prompt.split("\n人工定向修订请求（JSON）：", 1)[1].split("\n人工指令适用规则：", 1)[0])
        self.assertEqual(request["scope"], "all_claims")
        self.assertEqual(request["target_claim_ids"], [claim["claim_id"] for claim in state["claims"]])
        self.assertEqual([target["original_text"] for target in request["targets"]],
                         [claim["claim_text"] for claim in state["claims"]])
        self.assertFalse(state["manual_review_request"]["applied"])

    async def test_revision_uses_candidates_without_replaying_cached_invalid_output(self):
        state = {"query": "Scoped synthetic review", "phase": "revising", "errors": [],
                 "science_sections": [{"id": "s", "title": "Results"}], "draft_sections": {}}
        row = register_evidence(state, local_row(content="Exact source with against500 documents; not real results."), local=True)
        claim = normalize_paragraph(state, "A scoped synthetic statement", [row["evidence_id"]], "s", 0,
                                    evidence_links=[{"evidence_id": row["evidence_id"], "quote": "against 500 documents"}])
        claim["verification_status"] = "insufficient"
        state["claims"] = [claim]
        candidate = evidence_quote_candidates(row)[0]
        response = {"revisions": [{"claim_id": claim["claim_id"], "text": "A scoped synthetic statement",
                                   "evidence_ids": [row["evidence_id"]],
                                   "evidence_links": [{"evidence_id": row["evidence_id"], "quote_id": candidate["quote_id"]}]}]}
        agent = SimpleNamespace(add_message=lambda *args, **kwargs: None)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock, return_value=response) as call:
            await revise_science(agent, state)
        self.assertIs(call.call_args.kwargs["use_cache"], False)
        self.assertIn(candidate["quote_id"], call.call_args.args[1])
        self.assertFalse(claim["evidence_link_errors"])
        self.assertEqual(claim["verification_status"], "pending")
        self.assertEqual(state["phase"], "reviewing")


class ReportOutcomeTests(unittest.TestCase):
    def test_local_report_counts_sources_and_marks_failed_claims_in_body(self):
        state = {"query": "Local review", "science_sections": [{"id": "s", "title": "Findings"}],
                 "research_outcome": "completed_with_warnings", "review_verdict": "needs_revision",
                 "stop_reason": "review_budget_exhausted", "quality_review_status": "confirmed"}
        evidence = register_evidence(state, local_row(), local=True)
        claim = normalize_paragraph(state, "Unproven assertion", [evidence["evidence_id"]], "s", 0)
        claim.update(verification_status="contradicted", reason="Original evidence contradicts assertion")
        state["claims"] = [claim]
        report = render_science_report(state)
        self.assertIn("1 篇文献", report)
        self.assertIn("授权本地文档 1 篇", report)
        self.assertIn("未获全部审核通过", report)
        self.assertIn("与证据冲突", report)
        self.assertIn("review_budget_exhausted", report)
        self.assertIn("Original evidence contradicts assertion", report)

    def test_passed_outcome_cannot_hide_unsupported_claim(self):
        state = {"query": "Review", "research_outcome": "passed", "review_verdict": "pass",
                 "claims": [{"claim_id": "c", "claim_text": "Unknown", "evidence_ids": [], "verification_status": "unverified"}]}
        self.assertIn("未获全部审核通过", render_science_report(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
