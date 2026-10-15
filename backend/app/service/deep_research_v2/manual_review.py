"""Track manual text edits against request-time baselines, not review verdicts.

``applied`` records observable implementation of a manual edit. It is never a
claim that the resulting text is true or that the complete report passed review.
The ordinary Reviewer remains responsible for those decisions.
"""
from hashlib import sha256
import re


SCHEMA_VERSION = 2
_COMPLETED_HYPOTHESIS_REVIEW = {"confirmed", "not_needed"}


def _text(value):
    return value if isinstance(value, str) else ""


def text_hash(value):
    """Hash the exact text so stored baselines and current bodies are auditable."""
    return sha256(_text(value).encode("utf-8")).hexdigest()


def _comparison_hash(value):
    # Formatting-only edits do not implement a requested change to the body.
    return text_hash(re.sub(r"\s+", " ", _text(value)).strip())


def _claim_index(claims):
    rows, duplicates = {}, set()
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        cid = claim.get("claim_id")
        if not isinstance(cid, str) or not cid:
            continue
        if cid in rows:
            duplicates.add(cid)
        rows[cid] = claim
    return rows, duplicates


def _requested_ids(manual):
    return list(dict.fromkeys(cid for cid in manual.get("claim_ids", [])
                              if isinstance(cid, str) and cid))


def _hypothesis_index(hypotheses):
    ids, duplicates, invalid = [], set(), 0
    for row in hypotheses or []:
        hid = row.get("id") if isinstance(row, dict) else None
        if not isinstance(hid, str) or not hid:
            invalid += 1
        elif hid in ids:
            duplicates.add(hid)
        else:
            ids.append(hid)
    return ids, duplicates, invalid


def _legacy_baseline(state, manual):
    """Recover only the exact pre-request archive, never the already-edited body."""
    requested_at = manual.get("requested_at")
    if not requested_at:
        return None
    matches = []
    for entry in state.get("review_history") or []:
        if not isinstance(entry, dict) or entry.get("resumed_at") != requested_at:
            continue
        if entry.get("review_notes") != manual.get("notes"):
            continue
        if set(entry.get("review_claim_ids") or []) != set(_requested_ids(manual)):
            continue
        archived = entry.get("state")
        if isinstance(archived, dict) and isinstance(archived.get("claims"), list):
            matches.append(archived)
    # Ambiguous history must not silently choose a convenient baseline.
    return matches[0] if len(matches) == 1 else None


def initialize_manual_review(state, manual, *, new_request=False):
    """Freeze a new request or conservatively migrate an archived old request.

    Call with ``new_request=True`` only at the point that a new user request is
    accepted, before Writer mutates any claim. Existing v2 requests are refreshed
    without rebasing. Legacy requests without a matching original archive remain
    unconfirmed, even if an old ``applied`` flag happens to be true.
    """
    if not isinstance(manual, dict) or not _text(manual.get("notes")).strip():
        return manual
    if manual.get("schema_version") == SCHEMA_VERSION and not new_request:
        return _refresh(state, manual)

    requested = _requested_ids(manual)
    original = state if new_request else _legacy_baseline(state, manual)
    baseline, duplicates = _claim_index(original.get("claims") if original else [])
    target_ids = requested or list(baseline)
    if not target_ids and original is None:
        # Preserve known scope for diagnostics, but do not fabricate original text.
        current, _ = _claim_index(state.get("claims"))
        target_ids = requested or list(current)
    targets = []
    for cid in target_ids:
        claim = baseline.get(cid)
        body = _text(claim.get("claim_text")) if claim else None
        valid = bool(claim and cid not in duplicates and body and body.strip())
        targets.append({"claim_id": cid, "baseline_text": body if valid else None,
                        "baseline_hash": text_hash(body) if valid else None,
                        "baseline_comparison_hash": _comparison_hash(body) if valid else None})

    hypothesis_ids, duplicate_hypotheses, invalid_hypotheses = _hypothesis_index(
        (original or {}).get("hypotheses"))
    manual.update(schema_version=SCHEMA_VERSION, scope="selected_claims" if requested else "all_claims",
                  target_claim_ids=target_ids, targets=targets,
                  baseline_source="request" if new_request else "review_history" if original else "unavailable",
                  baseline_status="captured" if new_request else "recovered" if original else "unconfirmed",
                  hypothesis_ids=hypothesis_ids,
                  hypothesis_baseline_ambiguous_ids=sorted(duplicate_hypotheses),
                  hypothesis_baseline_invalid_count=invalid_hypotheses, revised_claim_ids=[],
                  changed_claim_ids=[], unchanged_requested_claim_ids=list(target_ids), revision_events=[],
                  applied=False, verification_status="unconfirmed")
    if requested:
        manual["hypothesis_review_status"] = "not_requested"
    elif original is not None and not hypothesis_ids:
        manual["hypothesis_review_status"] = "not_needed"
    elif new_request:
        manual["hypothesis_review_status"] = "pending"
    # A legacy global hypothesis result is preserved only alongside a recovered
    # baseline. It still cannot satisfy a missing or unchanged text target.
    elif original is None:
        manual["hypothesis_review_status"] = "unconfirmed"
    return _refresh(state, manual)


def _refresh(state, manual):
    claims, duplicates = _claim_index(state.get("claims"))
    targets = manual.get("targets") or []
    target_ids = manual.get("target_claim_ids") or []
    valid_structure = (len(targets) == len(target_ids)
                       and len(set(target_ids)) == len(target_ids)
                       and [row.get("claim_id") for row in targets if isinstance(row, dict)] == target_ids)
    changed, pending, missing = [], [], []
    verification = []
    for target in targets:
        if not isinstance(target, dict):
            valid_structure = False
            continue
        cid = target.get("claim_id")
        claim = claims.get(cid)
        current = _text(claim.get("claim_text")) if claim else ""
        baseline = target.get("baseline_text")
        baseline_valid = (isinstance(baseline, str) and bool(baseline.strip())
                          and target.get("baseline_hash") == text_hash(baseline)
                          and target.get("baseline_comparison_hash") == _comparison_hash(baseline))
        target["current_hash"] = text_hash(current) if claim else None
        target["current_comparison_hash"] = _comparison_hash(current) if claim else None
        target["verification_status"] = claim.get("verification_status", "pending") if claim else "missing"
        verification.append(target["verification_status"])
        if not baseline_valid:
            status = "baseline_unconfirmed"
        elif not claim or cid in duplicates:
            status = "missing" if not claim else "ambiguous"
            missing.append(cid)
        elif not current.strip():
            status = "empty"
        elif target["current_comparison_hash"] == target["baseline_comparison_hash"]:
            status = "unchanged"
        else:
            status = "changed"
            changed.append(cid)
        target["status"] = status
        if status != "changed":
            pending.append(cid)

    claims_applied = valid_structure and bool(targets) and not pending
    selected = manual.get("scope") == "selected_claims"
    if selected:
        manual["hypothesis_review_status"] = "not_requested"
    current_hypotheses, duplicate_hypotheses, _ = _hypothesis_index(state.get("hypotheses"))
    frozen_hypotheses = manual.get("hypothesis_ids") or []
    missing_hypotheses = sorted(set(frozen_hypotheses) - set(current_hypotheses)) if not selected else []
    ambiguous_hypotheses = sorted(set(frozen_hypotheses) & duplicate_hypotheses) if not selected else []
    hypothesis_scope_valid = (selected or (not missing_hypotheses and not ambiguous_hypotheses
                              and not manual.get("hypothesis_baseline_ambiguous_ids")
                              and not manual.get("hypothesis_baseline_invalid_count")))
    manual.update(missing_requested_hypothesis_ids=missing_hypotheses,
                  ambiguous_requested_hypothesis_ids=ambiguous_hypotheses,
                  hypothesis_scope_valid=hypothesis_scope_valid)
    if not hypothesis_scope_valid or (not selected and frozen_hypotheses
                                      and manual.get("hypothesis_review_status") == "not_needed"):
        manual["hypothesis_review_status"] = "unconfirmed"
    hypothesis_done = selected or (hypothesis_scope_valid
                                   and manual.get("hypothesis_review_status") in _COMPLETED_HYPOTHESIS_REVIEW)
    # A hypothesis-only global request can be completed without invented prose.
    hypotheses_only = (not selected and not targets and bool(manual.get("hypothesis_ids"))
                       and manual.get("baseline_source") != "unavailable")
    manual.update(changed_claim_ids=sorted(changed), unchanged_requested_claim_ids=sorted(pending),
                  missing_requested_claim_ids=sorted(missing),
                  applied=bool((claims_applied or hypotheses_only) and hypothesis_done),
                  text_applied=bool(claims_applied),
                  application_status="applied" if (claims_applied or hypotheses_only) and hypothesis_done
                                     else "partial" if changed else "pending")
    # The semantic disposition is independent of text application. In particular,
    # a changed paragraph may still be insufficient, contradicted or unverified.
    if not valid_structure or pending or not hypothesis_done or not verification:
        manual["verification_status"] = "unconfirmed"
    elif "contradicted" in verification:
        manual["verification_status"] = "contradicted"
    elif any(value in {"pending", "unverified", "missing"} for value in verification):
        manual["verification_status"] = "unconfirmed"
    elif "insufficient" in verification:
        manual["verification_status"] = "insufficient"
    elif all(value == "supported" for value in verification):
        manual["verification_status"] = "confirmed"
    else:
        manual["verification_status"] = "unconfirmed"
    return manual


def update_manual_progress(state, manual, revised_ids=()):
    """Refresh cumulative implementation and current target verification status.

    ``revised_ids`` contains edits actually accepted by Writer's normalizer, not
    IDs merely proposed by a model. Automatic problems may appear there for the
    existing audit field; only frozen manual targets determine ``applied``.
    """
    initialize_manual_review(state, manual)
    if not isinstance(manual, dict) or manual.get("schema_version") != SCHEMA_VERSION:
        return manual
    claims, duplicates = _claim_index(state.get("claims"))
    accepted = sorted({cid for cid in revised_ids if cid in claims and cid not in duplicates})
    prior = {cid for cid in manual.get("revised_claim_ids", []) if isinstance(cid, str)}
    manual["revised_claim_ids"] = sorted(prior | set(accepted))
    _refresh(state, manual)
    if accepted:
        events = manual.setdefault("revision_events", [])
        events.append({"iteration": state.get("iteration"), "revised_claim_ids": accepted,
                       "changed_target_ids": list(manual["changed_claim_ids"]),
                       "target_hashes": {row["claim_id"]: row.get("current_hash")
                                         for row in manual.get("targets", [])}})
        # Request and retry budgets bound ordinary history; cap corrupt/legacy
        # imported histories without claiming omitted events never happened.
        if len(events) > 20:
            manual["omitted_revision_events"] = manual.get("omitted_revision_events", 0) + len(events) - 20
            del events[:-20]
    return manual
