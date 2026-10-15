"""Check what the reviewer actually read, separately from citation positions.

This is a conservative contract, not a second factual oracle. A valid response
still needs semantic review. Corpus search cannot establish universal absence.
"""
import re
from collections import Counter

REVIEW_CONTRACT_VERSION = 2
STATUSES = {"supported", "contradicted", "insufficient", "unverified"}
RELATIONS = {"supports", "contradicts", "insufficient", "unreadable"}
REASON_CODES = {"content_checked", "content_unavailable", "semantic_uncertain"}


def build_review_materials(evidence_rows):
    """Describe only the exact bounded content in this request, not full ledger.

    Locator tags, quote candidates and writer link verification do not belong
    in semantic input. Asset content retains hydration/omission boundaries.
    """
    materials = []
    for row in evidence_rows:
        text = str(row.get("text") or "")
        level = row.get("evidence_level") or "metadata"
        text_readable = bool(text.strip()) and level != "metadata"
        assets = [{key: asset[key] for key in ("asset_id", "type", "content", "context_text", "content_truncated", "hydration") if key in asset}
                  for asset in row.get("assets") or [] if isinstance(asset, dict)]
        readable_assets = [a for a in assets if a.get("type") != "image"
                           and str(a.get("content") or a.get("context_text") or "").strip()
                           and (a.get("hydration") or {}).get("status") in {"complete", "partial"}]
        availability = {
            "text_available": text_readable, "text_chars": len(text),
            "content_available": text_readable or bool(readable_assets),
            "text_truncated": bool(row.get("text_truncated")),
            "readable_asset_ids": [a.get("asset_id") for a in readable_assets],
            "visual_content_verified": False,
            "assets_omitted_for_budget": row.get("assets_omitted_for_budget", 0),
        }
        materials.append({"evidence_id": row["evidence_id"], "title": row.get("title"),
                          "year": row.get("year"), "evidence_level": level,
                          "text": text, "text_truncated": bool(row.get("text_truncated")),
                          "assets": assets, "availability": availability})
    return materials


def scope_overreach(text):
    """Recognize explicit universal-absence wording, never arbitrary truth.

    A bounded corpus statement or an attributed experimental negative result
    remains for semantic review. The rule does not claim exhaustive NLP.
    """
    problems = []
    for sentence in re.split(r"[。；;\n]|因此|这说明|这表明|\btherefore\b|\bhence\b|(?<=[A-Za-z])\.(?=\s+[A-Z])", str(text), flags=re.I):
        # Remove a disclaimer before checking its substantive preceding clause.
        sentence = re.split(r"不能(?:据此)?(?:推断|说明|证明)|不(?:能|应)外推|does not (?:imply|prove)", sentence, flags=re.I)[0]
        if not sentence.strip():
            continue
        bounded = re.search(r"本次(?:检索|样本|语料|纳入|证据|研究)|当前(?:证据库|语料|检索集)|已纳入|这些(?:摘要|论文|文献)|所检索|本研究样本|(?:in|within|among) (?:the |our )?(?:retrieved|included|sampled|current corpus)", sentence, re.I)
        universal = re.search(r"(?:整个|全)?领域.{0,35}(?:尚无|不存在|从未|没有)|(?:尚无|不存在|没有任何).{0,55}(?:真实研究|真实文献|论文|研究)|(?:所有|任何|全部)(?:真实)?(?:研究|文献|论文).{0,30}(?:均未|没有|未提供|不存在)|真实(?:文献|研究)中.{0,30}(?:尚无|从未|不存在)|\b(?:no (?:published |real |prior )?(?:studies|study|papers|research)|never (?:been )?(?:studied|reported)|does not exist in (?:the )?(?:field|literature))\b", sentence, re.I)
        attributed = re.search(r"(?:作者|该论文|该研究|原文).{0,8}(?:报告|指出|认为)|(?:authors?|the study) (?:report|found)", sentence, re.I)
        experiment = re.search(r"该实验|此实验|该设置|该样本|(?:this|the) experiment", sentence, re.I)
        explicit_domain = re.search(r"领域.{0,20}(?:尚无|不存在|从未|没有)|所有真实(?:研究|文献|论文).{0,20}(?:均未|没有|未提供)", sentence)
        if universal and (not bounded or explicit_domain) and not (attributed and experiment):
            problems.append("domain_absence_from_sample")
    return list(dict.fromkeys(problems))


def validate_review_response(response, claims, materials):
    """Return accepted rows and per-claim violations; never accept partial IDs.

    Contract errors get one caller-controlled targeted retry. Scope violations
    are completed semantic failures (insufficient), rather than service errors.
    """
    known = {c["claim_id"]: c for c in claims}
    material_map = {m["evidence_id"]: m for m in materials}
    raw = response.get("results") if isinstance(response, dict) else None
    if not isinstance(raw, list):
        return [], {cid: ["results_not_list"] for cid in known}
    ids = [r.get("claim_id") for r in raw if isinstance(r, dict)]
    # Unknown output identities poison this response; never attach their facts
    # to a known claim by order. Duplicate known IDs invalidate only that row.
    foreign = any(not isinstance(r, dict) or not isinstance(r.get("claim_id"), str) or r["claim_id"] not in known for r in raw)
    counts = Counter(i for i in ids if isinstance(i, str))
    mapping = {r["claim_id"]: r for r in raw if isinstance(r, dict) and isinstance(r.get("claim_id"), str) and r["claim_id"] in known}
    accepted, violations = [], {}
    for cid, claim in known.items():
        errors, row = [], mapping.get(cid, {})
        if foreign:
            errors.append("foreign_claim_id")
        if counts.get(cid, 0) != 1:
            errors.append("missing_or_duplicate_claim_id")
        status, reason_code = row.get("status"), row.get("reason_code")
        if not isinstance(status, str) or status not in STATUSES or not isinstance(row.get("reason"), str) or not row["reason"].strip():
            errors.append("invalid_status_or_reason")
        if not isinstance(reason_code, str) or reason_code not in REASON_CODES:
            errors.append("missing_reason_code")
        expected = list(dict.fromkeys(claim.get("evidence_ids") or []))
        checks = row.get("evidence_checks")
        if not isinstance(checks, list):
            checks = []
            errors.append("missing_evidence_checks")
        check_ids = [c.get("evidence_id") for c in checks if isinstance(c, dict)]
        if (any(not isinstance(c, dict) for c in checks) or len(check_ids) != len(set(i for i in check_ids if isinstance(i, str)))
                or set(i for i in check_ids if isinstance(i, str)) != set(expected)):
            errors.append("evidence_check_identity_mismatch")
        for check in checks:
            if not isinstance(check, dict):
                continue
            eid, relation = check.get("evidence_id"), check.get("relation")
            material = material_map.get(eid) if isinstance(eid, str) else None
            if not material or eid not in expected:
                errors.append("unknown_evidence_id")
                continue
            available = material["availability"]["content_available"]
            if not isinstance(relation, str) or relation not in RELATIONS or not isinstance(check.get("reason"), str) or not check["reason"].strip():
                errors.append("invalid_evidence_check")
            elif relation == "unreadable" and available:
                errors.append("available_content_marked_unreadable")
            elif relation in {"supports", "contradicts"} and not available:
                errors.append("unavailable_content_used_as_support")
            # Optional extracts must be exact in the presented text/assets.
            quote = check.get("quote")
            visible = [material.get("text") or ""] + [str(a.get("content") or a.get("context_text") or "") for a in material.get("assets", [])]
            if quote is not None and (not isinstance(quote, str) or not quote.strip() or not any(quote in value for value in visible)):
                errors.append("review_quote_not_presented")
        readable = any(material_map.get(eid, {}).get("availability", {}).get("content_available") for eid in expected)
        if status == "supported" and (not expected or not any(c.get("relation") == "supports" for c in checks if isinstance(c, dict))):
            errors.append("supported_without_direct_evidence")
        if status == "supported" and any(c.get("relation") == "contradicts" for c in checks if isinstance(c, dict)):
            errors.append("supported_with_conflicting_evidence")
        if status == "contradicted" and not any(c.get("relation") == "contradicts" for c in checks if isinstance(c, dict)):
            errors.append("contradiction_without_evidence")
        if reason_code == "content_unavailable" and readable:
            errors.append("available_content_marked_missing")
        if isinstance(status, str) and status in {"supported", "contradicted"} and reason_code != "content_checked":
            errors.append("unchecked_verdict")
        if errors:
            violations[cid] = list(dict.fromkeys(errors))
            continue
        scope_errors = scope_overreach(claim.get("claim_text", ""))
        checked_row = {"claim_id": cid, "status": status, "reason": row["reason"].strip(),
                       "reason_code": reason_code, "evidence_checks": checks,
                       "review_contract_version": REVIEW_CONTRACT_VERSION, "scope_errors": scope_errors}
        if scope_errors and status == "supported":
            checked_row.update(status="insufficient", reason_code="scope_overreach",
                               reason="当前检索样本不能支持领域不存在或所有研究均无此结果的断言；请限定为本次已读材料的证据边界。")
        accepted.append(checked_row)
    return accepted, violations
