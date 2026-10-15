"""Offline regressions for request-scoped manual application and verification."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from service.deep_research_v2.manual_review import (
    initialize_manual_review, text_hash, update_manual_progress,
)


def claim(cid, text, status="supported"):
    return {"claim_id": cid, "claim_text": text, "verification_status": status}


def state_and_manual(*, ids=None, hypotheses=None):
    state = {"claims": [claim("selected", "Original target."), claim("automatic", "Automatic problem.", "insufficient")],
             "iteration": 1, "hypotheses": hypotheses or [], "review_verdict": "needs_revision",
             "quality_review_status": "unconfirmed", "unresolved_issues": 1}
    manual = {"notes": "Narrow the requested text.", "claim_ids": ["selected"] if ids is None else ids,
              "requested_at": "2026-10-15T00:00:00+00:00", "applied": False}
    state["manual_review_request"] = manual
    initialize_manual_review(state, manual, new_request=True)
    return state, manual


class ManualReviewStateTests(unittest.TestCase):
    def test_request_freezes_only_selected_target_with_exact_hashes(self):
        state, manual = state_and_manual()
        self.assertEqual(manual["target_claim_ids"], ["selected"])
        self.assertEqual(manual["targets"][0]["baseline_text"], "Original target.")
        self.assertEqual(manual["targets"][0]["baseline_hash"], text_hash("Original target."))
        self.assertEqual(manual["targets"][0]["current_hash"], text_hash("Original target."))
        self.assertEqual(manual["baseline_source"], "request")
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["hypothesis_review_status"], "not_requested")
        json.dumps(state)

    def test_applied_does_not_require_unrelated_automatic_problem_to_be_returned(self):
        state, manual = state_and_manual()
        state["claims"][0].update(claim_text="A narrower target.", verification_status="pending")
        update_manual_progress(state, manual, {"selected"})
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["verification_status"], "unconfirmed")
        self.assertEqual(state["claims"][1]["verification_status"], "insufficient")
        self.assertEqual(state["review_verdict"], "needs_revision")
        self.assertEqual(state["quality_review_status"], "unconfirmed")
        self.assertEqual(state["unresolved_issues"], 1)

    def test_later_unchanged_revision_keeps_original_baseline_and_prior_change(self):
        state, manual = state_and_manual()
        baseline = manual["targets"][0]["baseline_hash"]
        state["claims"][0]["claim_text"] = "A narrower target."
        update_manual_progress(state, manual, {"selected"})
        state["iteration"] = 2
        update_manual_progress(state, manual, {"automatic"})
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["changed_claim_ids"], ["selected"])
        self.assertEqual(manual["unchanged_requested_claim_ids"], [])
        self.assertEqual(manual["targets"][0]["baseline_hash"], baseline)
        self.assertEqual(manual["revised_claim_ids"], ["automatic", "selected"])
        self.assertEqual(len(manual["revision_events"]), 2)

    def test_reverting_to_original_revokes_application_without_losing_audit_history(self):
        state, manual = state_and_manual()
        state["claims"][0]["claim_text"] = "A narrower target."
        update_manual_progress(state, manual, {"selected"})
        state["claims"][0]["claim_text"] = "Original target."
        update_manual_progress(state, manual, {"selected"})
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["targets"][0]["status"], "unchanged")
        self.assertEqual(manual["changed_claim_ids"], [])
        self.assertEqual(manual["revision_events"][0]["changed_target_ids"], ["selected"])
        self.assertEqual(manual["revision_events"][1]["changed_target_ids"], [])

    def test_formatting_only_change_is_not_application(self):
        state, manual = state_and_manual()
        state["claims"][0]["claim_text"] = "  Original\n\ttarget.  "
        update_manual_progress(state, manual, {"selected"})
        target = manual["targets"][0]
        self.assertNotEqual(target["baseline_hash"], target["current_hash"])
        self.assertEqual(target["baseline_comparison_hash"], target["current_comparison_hash"])
        self.assertFalse(manual["applied"])

    def test_citation_only_edit_is_not_application(self):
        state, manual = state_and_manual()
        state["claims"][0]["evidence_links"] = [{"evidence_id": "ev_new", "quote_id": "quote_new"}]
        update_manual_progress(state, manual, {"selected"})
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["unchanged_requested_claim_ids"], ["selected"])

    def test_missing_or_empty_target_is_never_treated_as_completed_removal(self):
        for mode in ("missing", "empty"):
            with self.subTest(mode=mode):
                state, manual = state_and_manual()
                if mode == "missing":
                    state["claims"].pop(0)
                else:
                    state["claims"][0]["claim_text"] = " "
                update_manual_progress(state, manual, {"selected"})
                self.assertFalse(manual["applied"])
                self.assertEqual(manual["targets"][0]["status"], mode)

    def test_unknown_target_cannot_be_replaced_by_automatic_edit(self):
        state, manual = state_and_manual(ids=["absent"])
        state["claims"][1]["claim_text"] = "An automatic correction."
        update_manual_progress(state, manual, {"automatic"})
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["targets"][0]["status"], "baseline_unconfirmed")
        self.assertEqual(manual["changed_claim_ids"], [])

    def test_duplicate_current_target_is_ambiguous(self):
        state, manual = state_and_manual()
        state["claims"][0]["claim_text"] = "A narrower target."
        state["claims"].append(claim("selected", "A second different target."))
        update_manual_progress(state, manual, {"selected"})
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["targets"][0]["status"], "ambiguous")
        self.assertEqual(manual["revised_claim_ids"], [])

    def test_corrupted_baseline_or_scope_is_not_trusted(self):
        for field, value in (("baseline_text", "Tampered original."), ("baseline_hash", "wrong")):
            with self.subTest(field=field):
                state, manual = state_and_manual()
                state["claims"][0]["claim_text"] = "A narrower target."
                manual["targets"][0][field] = value
                update_manual_progress(state, manual, {"selected"})
                self.assertFalse(manual["applied"])
        state, manual = state_and_manual()
        state["claims"][0]["claim_text"] = "A narrower target."
        manual["target_claim_ids"].append("fabricated")
        update_manual_progress(state, manual, {"selected"})
        self.assertFalse(manual["applied"])

    def test_applied_and_semantic_verification_are_independent(self):
        for verdict in ("pending", "unverified", "insufficient", "contradicted", "supported"):
            with self.subTest(verdict=verdict):
                state, manual = state_and_manual()
                state["claims"][0].update(claim_text="A narrower target.", verification_status=verdict)
                update_manual_progress(state, manual, {"selected"})
                expected = {"pending": "unconfirmed", "unverified": "unconfirmed", "supported": "confirmed"}.get(verdict, verdict)
                self.assertTrue(manual["applied"])
                self.assertEqual(manual["verification_status"], expected)

    def test_selected_claim_does_not_reopen_or_require_unrequested_hypothesis(self):
        state, manual = state_and_manual(hypotheses=[{"id": "hyp", "status": "insufficient"}])
        state["claims"][0]["claim_text"] = "A narrower target."
        manual["hypothesis_review_status"] = "unconfirmed"
        before = copy.deepcopy(state["hypotheses"])
        update_manual_progress(state, manual, {"selected"})
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["hypothesis_review_status"], "not_requested")
        self.assertEqual(state["hypotheses"], before)

    def test_global_request_freezes_all_targets_and_requires_each_actual_change(self):
        state, manual = state_and_manual(ids=[])
        self.assertEqual(manual["target_claim_ids"], ["selected", "automatic"])
        state["claims"][0]["claim_text"] = "A narrower target."
        update_manual_progress(state, manual, {"selected"})
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["application_status"], "partial")
        state["claims"][1]["claim_text"] = "A narrower automatic statement."
        update_manual_progress(state, manual, {"automatic"})
        self.assertTrue(manual["applied"])
        # New report additions after the request do not expand its frozen scope.
        state["claims"].append(claim("new", "New additional coverage."))
        update_manual_progress(state, manual)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["target_claim_ids"], ["selected", "automatic"])

    def test_global_request_requires_its_requested_hypothesis_review_but_not_support(self):
        state, manual = state_and_manual(ids=[], hypotheses=[{"id": "hyp", "status": "insufficient"}])
        for row in state["claims"]:
            row["claim_text"] += " Scope narrowed."
        update_manual_progress(state, manual, {"selected", "automatic"})
        self.assertFalse(manual["applied"])
        self.assertTrue(manual["text_applied"])
        manual["hypothesis_review_status"] = "unconfirmed"
        update_manual_progress(state, manual)
        self.assertFalse(manual["applied"])
        manual["hypothesis_review_status"] = "confirmed"
        update_manual_progress(state, manual)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["verification_status"], "insufficient")
        self.assertEqual(state["hypotheses"][0]["status"], "insufficient")

    def test_global_hypothesis_only_request_does_not_require_invented_claim(self):
        state, manual = state_and_manual(ids=[], hypotheses=[{"id": "hyp"}])
        state["claims"] = []
        initialize_manual_review(state, manual, new_request=True)
        self.assertFalse(manual["applied"])
        manual["hypothesis_review_status"] = "confirmed"
        update_manual_progress(state, manual)
        self.assertTrue(manual["applied"])
        self.assertFalse(manual["text_applied"])

    def test_global_missing_requested_hypothesis_cannot_be_not_needed(self):
        state, manual = state_and_manual(ids=[], hypotheses=[{"id": "requested_hyp"}])
        for row in state["claims"]:
            row["claim_text"] += " Scope narrowed."
        state["hypotheses"] = []
        manual["hypothesis_review_status"] = "not_needed"
        update_manual_progress(state, manual, {"selected", "automatic"})
        self.assertFalse(manual["applied"])
        self.assertFalse(manual["hypothesis_scope_valid"])
        self.assertEqual(manual["missing_requested_hypothesis_ids"], ["requested_hyp"])
        self.assertEqual(manual["hypothesis_review_status"], "unconfirmed")

    def test_global_duplicate_requested_hypothesis_id_is_not_confirmed(self):
        for duplicated_at in ("baseline", "current"):
            with self.subTest(duplicated_at=duplicated_at):
                hypotheses = [{"id": "requested_hyp"}]
                if duplicated_at == "baseline":
                    hypotheses *= 2
                state, manual = state_and_manual(ids=[], hypotheses=hypotheses)
                state["hypotheses"] = [{"id": "requested_hyp"}, {"id": "requested_hyp"}]
                for row in state["claims"]:
                    row["claim_text"] += " Scope narrowed."
                manual["hypothesis_review_status"] = "confirmed"
                update_manual_progress(state, manual)
                self.assertFalse(manual["applied"])
                self.assertEqual(manual["ambiguous_requested_hypothesis_ids"], ["requested_hyp"])
                self.assertEqual(manual["hypothesis_review_status"], "unconfirmed")

    def test_new_hypothesis_does_not_expand_global_manual_request_scope(self):
        state, manual = state_and_manual(ids=[], hypotheses=[{"id": "requested_hyp"}])
        for row in state["claims"]:
            row["claim_text"] += " Scope narrowed."
        state["hypotheses"].extend([{"id": "new_hyp"}, {"id": "new_hyp"}])
        manual["hypothesis_review_status"] = "confirmed"
        update_manual_progress(state, manual)
        self.assertTrue(manual["applied"])
        self.assertTrue(manual["hypothesis_scope_valid"])
        self.assertEqual(manual["hypothesis_ids"], ["requested_hyp"])

    def test_frozen_hypothesis_cannot_be_skipped_with_not_needed_even_if_present(self):
        state, manual = state_and_manual(ids=[], hypotheses=[{"id": "requested_hyp"}])
        for row in state["claims"]:
            row["claim_text"] += " Scope narrowed."
        manual["hypothesis_review_status"] = "not_needed"
        update_manual_progress(state, manual)
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["hypothesis_review_status"], "unconfirmed")

    def legacy(self):
        state, manual = state_and_manual()
        original = copy.deepcopy(state)
        manual.clear()
        manual.update(notes="Narrow the requested text.", claim_ids=["selected"],
                      requested_at="2026-10-15T00:00:00+00:00", applied=False,
                      changed_claim_ids=[], revised_claim_ids=["automatic"], hypothesis_review_status="unconfirmed")
        state["review_history"] = [{"resumed_at": manual["requested_at"], "review_notes": manual["notes"],
                                    "review_claim_ids": ["selected"], "state": original}]
        state["claims"][0]["claim_text"] = "A narrower target."
        return state, manual

    def test_legacy_matching_request_archive_recovers_real_change_without_old_changed_flag(self):
        state, manual = self.legacy()
        initialize_manual_review(state, manual)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["baseline_source"], "review_history")
        self.assertEqual(manual["baseline_status"], "recovered")
        self.assertEqual(manual["targets"][0]["baseline_hash"], text_hash("Original target."))
        self.assertEqual(manual["targets"][0]["current_hash"], text_hash("A narrower target."))
        self.assertEqual(manual["changed_claim_ids"], ["selected"])
        # Re-initialization must never rebase onto the already-modified body.
        initialize_manual_review(state, manual)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["targets"][0]["baseline_text"], "Original target.")

    def test_legacy_old_applied_true_does_not_override_unchanged_current_body(self):
        state, manual = self.legacy()
        state["claims"][0]["claim_text"] = "Original target."
        manual.update(applied=True, changed_claim_ids=["selected"])
        initialize_manual_review(state, manual)
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["targets"][0]["status"], "unchanged")

    def test_legacy_mismatched_or_missing_archive_never_invents_request_baseline(self):
        for changed in ("missing", "time", "notes", "ids", "ambiguous"):
            with self.subTest(changed=changed):
                state, manual = self.legacy()
                manual["applied"] = True
                if changed == "missing":
                    state["review_history"] = []
                elif changed == "ambiguous":
                    state["review_history"] *= 2
                else:
                    field = {"time": "resumed_at", "notes": "review_notes", "ids": "review_claim_ids"}[changed]
                    state["review_history"][0][field] = ["other"] if changed == "ids" else "different"
                initialize_manual_review(state, manual)
                self.assertFalse(manual["applied"])
                self.assertEqual(manual["baseline_source"], "unavailable")
                self.assertIsNone(manual["targets"][0]["baseline_hash"])

    def test_legacy_without_requested_at_requires_explicit_new_request_initialization(self):
        state, manual = self.legacy()
        manual.pop("requested_at")
        initialize_manual_review(state, manual)
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["baseline_source"], "unavailable")
        initialize_manual_review(state, manual, new_request=True)
        self.assertEqual(manual["targets"][0]["baseline_text"], "A narrower target.")
        self.assertFalse(manual["applied"])
        state["claims"][0]["claim_text"] = "Further narrowed new request."
        update_manual_progress(state, manual, {"selected"})
        self.assertTrue(manual["applied"])

    def test_new_manual_request_rebases_explicitly_without_carrying_old_completion(self):
        state, manual = state_and_manual()
        state["claims"][0]["claim_text"] = "A narrower target."
        update_manual_progress(state, manual, {"selected"})
        manual.update(notes="Make another independent edit.", requested_at="2026-10-15T01:00:00+00:00")
        initialize_manual_review(state, manual, new_request=True)
        self.assertFalse(manual["applied"])
        self.assertEqual(manual["targets"][0]["baseline_text"], "A narrower target.")
        self.assertEqual(manual["revised_claim_ids"], [])
        self.assertEqual(manual["revision_events"], [])

    def test_revision_events_are_bounded_and_refresh_does_not_add_fake_writer_event(self):
        state, manual = state_and_manual()
        state["claims"][0]["claim_text"] = "A narrower target."
        for number in range(23):
            state["iteration"] = number
            update_manual_progress(state, manual, {"selected", "not_a_real_claim"})
        self.assertEqual(len(manual["revision_events"]), 20)
        self.assertEqual(manual["omitted_revision_events"], 3)
        self.assertEqual(manual["revised_claim_ids"], ["selected"])
        events = copy.deepcopy(manual["revision_events"])
        update_manual_progress(state, manual)
        self.assertEqual(manual["revision_events"], events)

    def test_no_request_is_a_noop(self):
        state, manual = state_and_manual()
        empty = {"notes": " "}
        self.assertIs(initialize_manual_review(state, empty), empty)
        self.assertIs(update_manual_progress(state, empty), empty)
        self.assertNotIn("applied", empty)


class ManualReviewWriterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_writer_selected_change_does_not_require_returning_automatic_failure(self):
        from service.deep_research_v2.evidence import register_evidence, normalize_paragraph
        from service.deep_research_v2.science_roles import revise_science

        state = {"query": "Inspect a synthetic local source.", "phase": "revising", "iteration": 1,
                 "max_iterations": 3, "errors": [], "science_sections": [{"id": "s", "title": "Results"}],
                 "draft_sections": {}, "review_verdict": "needs_revision", "quality_review_status": "unconfirmed"}
        evidence = register_evidence(state, {"document_id": "doc", "knowledge_base_id": "kb",
            "document_version": "v1", "chunk_id": "chunk", "title": "Synthetic source",
            "content": "Only this synthetic experiment compares the reported methods. " * 6,
            "verified": True}, local=True)
        selected = normalize_paragraph(state, "An overly broad field-wide claim.", [evidence["evidence_id"]], "s", 0)
        automatic = normalize_paragraph(state, "A separate unsupported statement.", [evidence["evidence_id"]], "s", 1)
        selected["verification_status"], automatic["verification_status"] = "supported", "insufficient"
        state["claims"] = [selected, automatic]
        manual = {"notes": "Only narrow the selected claim to the synthetic experiment.",
                  "claim_ids": [selected["claim_id"]], "requested_at": "2026-10-15T00:00:00Z"}
        state["manual_review_request"] = manual
        initialize_manual_review(state, manual, new_request=True)
        baseline = manual["targets"][0]["baseline_hash"]
        original_automatic = copy.deepcopy(automatic)
        response = {"revisions": [{"claim_id": selected["claim_id"],
                     "text": "Only this synthetic experiment compares the reported methods.",
                     "evidence_ids": [evidence["evidence_id"]]}]}
        agent = SimpleNamespace(add_message=lambda *args, **kwargs: None)
        with patch("service.deep_research_v2.science_roles.json_call", new_callable=AsyncMock,
                   return_value=response):
            await revise_science(agent, state)
        self.assertEqual(automatic, original_automatic)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["revised_claim_ids"], [selected["claim_id"]])
        self.assertEqual(manual["verification_status"], "unconfirmed")
        self.assertEqual(manual["targets"][0]["baseline_hash"], baseline)
        self.assertNotEqual(manual["targets"][0]["current_hash"], baseline)
        self.assertEqual(state["phase"], "reviewing")
        self.assertEqual(state["review_verdict"], "needs_revision")

        # The actual Reviewer updates claims later. Its semantic result changes
        # only verification, while the implemented body edit remains observable.
        selected["verification_status"] = "insufficient"
        update_manual_progress(state, manual)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["verification_status"], "insufficient")
        selected["verification_status"] = "supported"
        update_manual_progress(state, manual)
        self.assertTrue(manual["applied"])
        self.assertEqual(manual["verification_status"], "confirmed")
        self.assertEqual(automatic["verification_status"], "insufficient")
        self.assertEqual(state["quality_review_status"], "unconfirmed")


if __name__ == "__main__":
    unittest.main()
