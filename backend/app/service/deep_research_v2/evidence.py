"""Stable source/evidence identities and server-rendered scientific citations."""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlparse


def stable_id(prefix, value):
    return prefix + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def ensure_science_state(state):
    defaults = {"papers": [], "evidence_ledger": {}, "claims": [], "science_sections": [],
                "evidence_assessment": {}, "analysis_search_round": 0,
                "supplementary_origin": None, "return_phase": "revising",
                "claim_verification": {}, "citation_errors": [], "literature_errors": [],
                "corpus_statistics": {}, "profile_id": "science"}
    for key, value in defaults.items():
        state.setdefault(key, value.copy() if isinstance(value, (list, dict)) else value)
    return state


def scientific(state):
    return (state.get("research_profile") or {}).get("mode") == "science"


def canonical_source(row):
    doi = str(row.get("doi") or "").strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    if doi:
        return "doi:" + doi
    title = re.sub(r"[^\w]+", "", str(row.get("title") or "").casefold())
    if title:
        return "title:" + title
    return str(row.get("source_id") or row.get("url") or row.get("document_id") or "")


def research_sources(state):
    """One source per document/paper, independently of the retrieval channel.

    Evidence remains chunk-grained. Never count ten chunks from one local file
    as ten papers. Legacy paper-only checkpoints are retained until migrated.
    """
    ledger = state.get("evidence_ledger", {})
    rows = list(ledger.values())
    known = {row.get("source_id") for row in rows}
    rows.extend(row for row in state.get("papers", []) if row.get("source_id") not in known
                and row.get("evidence_id") not in ledger)
    grouped = {}
    levels = {"metadata": 0, "abstract": 1, "local_text": 2, "full_text": 3}
    for row in rows:
        source_id = row.get("source_id")
        if not source_id:
            continue
        identity = canonical_source(row)
        # Only an explicit valid DOI may join distinct local/Web identities.
        # A similar title is not enough to merge independent uploaded files.
        canonical_id = stable_id("src_", identity) if re.match(r"^doi:10\.\d{4,9}/\S+$", identity) else source_id
        previous = grouped.get(canonical_id)
        ids = list(dict.fromkeys((previous or {}).get("evidence_ids", []) +
                                ([row["evidence_id"]] if row.get("evidence_id") else [])))
        aliases = list(dict.fromkeys((previous or {}).get("source_aliases", []) + [source_id]))
        origins = list(dict.fromkeys((previous or {}).get("source_types", []) +
                                    ["local" if row.get("document_id") else "web"]))
        versions = list((previous or {}).get("document_versions", []))
        if row.get("document_id"):
            version = {key: row.get(key) for key in ("knowledge_base_id", "document_id", "document_version")}
            if version not in versions:
                versions.append(version)
        strength = lambda value: (levels.get(value.get("evidence_level"), 0), len(value.get("content") or ""))
        if previous is None or strength(row) > strength(previous):
            grouped[canonical_id] = {**row}
        grouped[canonical_id].update(source_id=canonical_id, evidence_ids=ids, source_aliases=aliases,
                                     source_types=origins, document_versions=versions)
    def order(row):
        try:
            year = int(row.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        return year, str(row.get("title") or ""), row["source_id"]
    return sorted(grouped.values(), key=order)


def sync_sources(state):
    """Keep the public corpus view consistent with the authoritative ledger."""
    state["papers"] = research_sources(state)
    return state["papers"]


def _merge_asset_contexts(previous, incoming):
    """Retain acquired context on a repeated query without unbounded growth.

    Earlier quote/span pointers remain valid: new excerpts append to, rather
    than replace, the old asset context. This does not upgrade visual evidence.
    """
    by_id = {asset.get("asset_id"): asset for asset in previous if asset.get("asset_id")}
    for asset in incoming:
        key = asset.get("asset_id")
        old = by_id.get(key)
        if not old or old.get("document_version") != asset.get("document_version"):
            by_id[key] = asset
            continue
        if (old.get("hydration") or {}).get("status") == "complete":
            continue
        if not old.get("hydration"):
            by_id[key] = asset
            continue
        old_text, new_text = str(old.get("content") or ""), str(asset.get("content") or "")
        if not new_text or new_text in old_text:
            continue
        rows = list((old.get("locator") or {}).get("table_rows") or [])
        for row in (asset.get("locator") or {}).get("table_rows") or []:
            if row not in rows:
                rows.append(row)
        text = old_text + ("\n" if old_text else "") + new_text
        if len(text) + len(json.dumps(rows, ensure_ascii=False)) > 16000 or len(rows) > 128:
            old["hydration"] = {**old["hydration"], "context_budget_reached": True}
            continue
        locator = {**(old.get("locator") or {})}
        if rows:
            locator["table_rows"] = rows
        by_id[key] = {**old, "content": text, "locator": locator, "content_truncated": True,
                      "hydration": {**old["hydration"], "status": "visual_unverified" if old.get("type") == "image" else "partial",
                                    "content_truncated": True, "reason": "累积保留已取得原文上下文，不能据此假定完整资产已读"}}
    return list(by_id.values())


def register_evidence(state, row, *, local=False):
    ensure_science_state(state)
    identity = ("document:" + str(row.get("document_id"))) if local and row.get("document_id") else canonical_source(row)
    if not identity or not row.get("title"):
        raise ValueError("来源缺少稳定身份或标题")
    url = str(row.get("url") or "")
    if not local and urlparse(url).scheme not in ("https", "http"):
        raise ValueError("网络文献必须提供真实 HTTP(S) 来源")
    source_id = stable_id("src_", identity)
    if not local:
        # Crossref and arXiv may identify the same paper by DOI and title. Keep
        # the first stable citation identity while allowing richer later text.
        title_key = re.sub(r"\W+", "", str(row["title"]).casefold())
        for prior in state["evidence_ledger"].values():
            if not prior.get("document_id") and (canonical_source(prior) == identity or
                    (not (prior.get("doi") and row.get("doi")) and
                     re.sub(r"\W+", "", str(prior.get("title", "")).casefold()) == title_key)):
                source_id = prior["source_id"]
                break
    # A local document can contain many independent chunks/assets.
    chunk_key = str(row.get("chunk_id") or row.get("asset_id") or "") if local else "abstract"
    evidence_id = stable_id("ev_", source_id + ":" + chunk_key)
    content = str(row.get("abstract") or row.get("content") or row.get("summary") or "").strip()
    locator = row.get("locator") or row.get("locators") or {"section": "摘要" if content else "文献元数据"}
    evidence = {
        "evidence_id": evidence_id, "source_id": source_id,
        "provider_source_id": row.get("source_id"), "provider_evidence_id": row.get("evidence_id"), "document_id": row.get("document_id"),
        "knowledge_base_id": row.get("knowledge_base_id"),
        "chunk_id": row.get("chunk_id"), "chunk_index": row.get("chunk_index"),
        "asset_ids": list(dict.fromkeys(list(row.get("asset_ids") or []) +
                                       [a["asset_id"] for a in row.get("assets", []) if a.get("asset_id")])),
        "text_start": row.get("text_start"), "text_end": row.get("text_end"),
        "title": row.get("title"), "url": url, "doi": row.get("doi"),
        "year": row.get("year"), "authors": row.get("authors") or [],
        "content": content, "abstract": str(row.get("abstract") or ""),
        "locator": locator, "locators": row.get("locators") or [], "assets": row.get("assets") or [],
        "download_url": row.get("download_url"), "document_version": row.get("document_version"),
        "provider": row.get("provider") or ("local" if local else "web"),
        "source_type": "local" if local else "web",
        "asset_hydration": row.get("asset_hydration") or {},
        "verified": bool(row.get("verified")), "verification": row.get("verification"),
        "evidence_level": row.get("evidence_level") or ("local_text" if local else "abstract" if content else "metadata"),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "document_type": row.get("document_type") or "article",
        "retrieved_at": row.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
    }
    previous = state["evidence_ledger"].get(evidence_id)
    if previous:
        evidence["assets"] = _merge_asset_contexts(previous.get("assets") or [], evidence["assets"])
        evidence["asset_ids"] = list(dict.fromkeys((previous.get("asset_ids") or []) + evidence["asset_ids"]))
        for field in ("knowledge_base_id", "document_version", "chunk_index", "text_start", "text_end"):
            if evidence.get(field) is None:
                evidence[field] = previous.get(field)
        levels = {"metadata": 0, "abstract": 1, "local_text": 2, "full_text": 3}
        old_strength = (levels.get(previous.get("evidence_level"), 1), len(previous.get("content", "")))
        new_strength = (levels.get(evidence.get("evidence_level"), 1), len(content))
        # Keep text, its declared evidence level and provenance together. A
        # later metadata-only match must never relabel an acquired abstract.
        if old_strength > new_strength:
            for field in ("content", "content_hash", "abstract", "evidence_level", "locator", "locators",
                          "verification", "provider", "download_url", "document_version"):
                evidence[field] = previous.get(field)
        for field in ("doi", "year", "authors", "url"):
            if not evidence.get(field):
                evidence[field] = previous.get(field)
        evidence["verified"] = bool(evidence["verified"] or previous.get("verified"))
        evidence["retrieved_at"] = previous.get("retrieved_at") or evidence["retrieved_at"]
    state["evidence_ledger"][evidence_id] = evidence
    sync_sources(state)
    return evidence


def merge_scientific_papers(state, rows, *, max_papers=None):
    """Merge acquired records and upgrades without invalidating existing citations."""
    ensure_science_state(state)
    existing = {p["source_id"]: p for p in state["papers"]}
    added, upgraded = [], []
    for row in rows:
        if not row.get("verified"):
            state["literature_errors"].append({"title": row.get("title"), "reason": "来源未核验，未计入纳入文献"})
            continue
        if max_papers is not None and len(existing) >= max_papers:
            identity = canonical_source(row)
            title_key = re.sub(r"\W+", "", str(row.get("title", "")).casefold())
            if not any(canonical_source(p) == identity or
                       (not (p.get("doi") and row.get("doi")) and
                        re.sub(r"\W+", "", str(p.get("title", "")).casefold()) == title_key)
                       for p in existing.values()):
                continue
        before = {key: (value.get("content_hash"), value.get("evidence_level"))
                  for key, value in state["evidence_ledger"].items()}
        try:
            evidence = register_evidence(state, row)
        except ValueError as exc:
            state["literature_errors"].append({"title": row.get("title"), "reason": str(exc)})
            continue
        evidence_id = evidence["evidence_id"]
        if evidence_id not in before:
            added.append(evidence_id)
        elif before[evidence_id] != (evidence.get("content_hash"), evidence.get("evidence_level")):
            upgraded.append(evidence_id)
        existing[evidence["source_id"]] = evidence
    sync_sources(state)
    return {"added": added, "upgraded": upgraded}


def references_from_ledger(state):
    result = []
    for evidence in research_sources(state):
        result.append({**evidence, "id": len(result) + 1, "source": evidence["title"],
                       "title": evidence["title"], "link": evidence["url"],
                       "marker": f"[{len(result) + 1}]"})
    return result


def citation_numbers(state):
    return {source_id: ref["id"] for ref in references_from_ledger(state)
            for source_id in [ref["source_id"]] + ref.get("source_aliases", [])}


def render_claim(state, claim):
    numbers = citation_numbers(state)
    ledger = state.get("evidence_ledger", {})
    links = []
    bound_local = {}
    for index, link in enumerate(claim.get("evidence_links") or []):
        row = ledger.get(link.get("evidence_id")) or {}
        # A chunk-only citation still needs the authenticated, version-scoped
        # viewer. This changes navigation, never its declared precision or proof.
        identity_fields = ("knowledge_base_id", "document_id", "document_version", "chunk_id")
        if (link.get("verification") in {"validated", "chunk_only"}
                and all(row.get(key) is not None and str(link.get(key)) == str(row[key]) for key in identity_fields)):
            bound_local.setdefault(link.get("evidence_id"), []).append(index)
    for evidence_id in dict.fromkeys(claim.get("evidence_ids", [])):
        row = ledger.get(evidence_id)
        if row:
            target = row["url"]
            if evidence_id in bound_local:
                for index in bound_local[evidence_id]:
                    target = f"#claim-evidence:{quote(str(claim['claim_id']), safe='')}:{index}"
                    links.append(f"[{numbers[row['source_id']]}]({target})")
            else:
                link = f"[{numbers[row['source_id']]}]({target})"
                if link not in links:
                    links.append(link)
    return claim["claim_text"].strip() + (" " + " ".join(links) if links else "")


def _locator_subset(requested, actual):
    """Only accept literal parser fields, never coordinates invented by a model."""
    return (isinstance(requested, dict) and bool(requested) and isinstance(actual, dict)
            and all(key in actual and value == actual[key] for key, value in requested.items()))


def _asset_locators(asset):
    locator = asset.get("locator") or {}
    if not isinstance(locator, dict):
        return []
    base = {key: value for key, value in locator.items() if key != "table_rows"}
    return [base] + [{**base, **{k: v for k, v in row.items() if k not in {"text", "cells", "content"}}}
                     for row in locator.get("table_rows", []) if isinstance(row, dict)]


def evidence_quote_candidates(evidence):
    """Deterministic verbatim spans, independent of a caller's prompt budget.

    IDs bind the exact acquired text, evidence, document version and optional
    hydrated asset. They prove a location only, never semantic claim support.
    No whitespace, punctuation, number or negation normalization is performed.
    """
    eid = evidence.get("evidence_id")
    if not eid:
        return []
    sources = [(None, str(evidence.get("content") or ""))]
    scope = evidence.get("asset_hydration") or {}
    if scope.get("authorized_scope") and scope.get("requested"):
        for asset in (evidence.get("assets") or [])[:8]:
            if (asset.get("asset_id") and asset.get("document_id") == evidence.get("document_id")
                    and asset.get("document_version") == evidence.get("document_version")
                    and (asset.get("hydration") or {}).get("status") in {"complete", "partial", "visual_unverified"}):
                sources.append((asset["asset_id"], str(asset.get("content") or "")))
    candidates, total_chars = [], 0
    for asset_id, content in sources:
        source_count = 0
        # Every span is copied from the unchanged source. Long lines are split
        # at a nearby space where possible, not reconstructed from tokens.
        for line in re.finditer(r"[^\r\n]+", content[:12000]):
            start, end = line.span()
            while start < end and content[start].isspace():
                start += 1
            while end > start and content[end - 1].isspace():
                end -= 1
            while start < end and source_count < 12:
                stop = min(start + 280, end)
                if stop < end:
                    boundary = content.rfind(" ", start + 140, stop)
                    if boundary > start:
                        stop = boundary
                excerpt = content[start:stop]
                if total_chars + len(excerpt) > 6000 or len(candidates) >= 40:
                    return candidates
                identity = json.dumps([eid, evidence.get("knowledge_base_id"), evidence.get("document_id"),
                                       evidence.get("document_version"), evidence.get("chunk_id"),
                                       asset_id, start, stop, excerpt], ensure_ascii=False, separators=(",", ":"))
                item = {"quote_id": stable_id("quote_", identity), "evidence_id": eid, "quote": excerpt,
                        "text_span": {"start": start, "end": stop},
                        "span_scope": "asset_context" if asset_id else "chunk_text"}
                if asset_id:
                    item["asset_id"] = asset_id
                candidates.append(item)
                total_chars += len(excerpt)
                source_count += 1
                start = stop
                while start < end and content[start].isspace():
                    start += 1
            if source_count >= 12:
                break
    return candidates


def normalize_evidence_links(state, evidence_ids, links=None):
    """Validate claim support pointers against acquired evidence, not LLM labels.

    A valid location proves provenance, NOT semantic support. Reviewer must still
    verify the claim. Missing/invalid pointers fall back to explicitly coarse
    chunk references; they never become precise links by guessing a location.
    """
    ledger = state.get("evidence_ledger", {})
    accepted, errors = [], []

    def reject(reason, eid=None, raw=None):
        item = {"reason": reason}
        if eid is not None:
            item["evidence_id"] = str(eid)
        # Keep repairable diagnostics without persisting unbounded model output.
        if isinstance(raw, dict) and len(errors) < 8:
            detail = {key: str(raw[key])[:100] for key in ("quote_id", "asset_id") if raw.get(key) is not None}
            if isinstance(raw.get("quote"), str):
                detail.update(quote_preview=raw["quote"][:280], quote_chars=len(raw["quote"]),
                              quote_truncated=len(raw["quote"]) > 280)
            for key in ("locator", "text_span"):
                if raw.get(key) is not None:
                    detail[key + "_preview"] = json.dumps(raw[key], ensure_ascii=False, default=str)[:240]
            if detail:
                item["rejected"] = detail
        errors.append(item)

    if links is not None and not isinstance(links, list):
        errors.append({"reason": "evidence_links 必须为数组"})
        links = []
    for raw in (links or [])[:30]:
        if not isinstance(raw, dict):
            errors.append({"reason": "无效引用定位对象"})
            continue
        eid = raw.get("evidence_id")
        submitted = raw
        evidence = ledger.get(eid) if isinstance(eid, str) and eid in evidence_ids else None
        if not evidence:
            reject("定位必须绑定本段已提供的证据", eid, submitted)
            continue
        if raw.get("quote_id") is not None:
            candidate = next((row for row in evidence_quote_candidates(evidence)
                              if row["quote_id"] == raw["quote_id"]), None)
            if candidate is None:
                reject("候选引文不存在于该证据或已授权展开资产中", eid, submitted)
                continue
            if (raw.get("asset_id") is not None and raw["asset_id"] != candidate.get("asset_id")
                    or raw.get("quote") is not None and raw["quote"] != candidate["quote"]
                    or raw.get("text_span") is not None and (
                        raw["text_span"] != candidate["text_span"] or not isinstance(raw["text_span"], dict)
                        or not all(type(raw["text_span"].get(key)) is int for key in ("start", "end")))):
                reject("候选引文与所填资产、逐字引文或原文跨度不一致", eid, submitted)
                continue
            raw = {**raw, "quote": candidate["quote"], "text_span": dict(candidate["text_span"])}
            if candidate.get("asset_id"):
                raw["asset_id"] = candidate["asset_id"]
        asset = None
        if raw.get("asset_id"):
            asset = next((a for a in evidence.get("assets", []) if a.get("asset_id") == raw["asset_id"]
                          and str(a.get("document_id")) == str(evidence.get("document_id"))
                          and a.get("document_version") == evidence.get("document_version")), None)
            if not asset:
                reject("资产不属于该证据文档版本", eid, submitted)
                continue
        candidates = _asset_locators(asset) if asset else evidence.get("locators") or []
        if not candidates and evidence.get("locator"):
            candidates = evidence["locator"] if isinstance(evidence["locator"], list) else [evidence["locator"]]
        locator = raw.get("locator")
        if locator == {}:
            locator = None  # Empty optional JSON is coarse, never precise.
        if locator is not None and not any(_locator_subset(locator, actual) for actual in candidates):
            reject("定位不在原始证据或已展开资产中", eid, submitted)
            continue
        content = str((asset or evidence).get("content") or "")
        excerpt = raw.get("quote")
        span = raw.get("text_span")
        if excerpt is not None and (not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in content):
            reject("引文不是所指证据的原文子串", eid, submitted)
            continue
        if span is not None:
            if (not isinstance(span, dict) or not all(type(span.get(k)) is int for k in ("start", "end"))
                    or not 0 <= span["start"] < span["end"] <= len(content)
                    or (excerpt is not None and content[span["start"]:span["end"]] != excerpt)):
                reject("原文偏移无效或与引文不一致", eid, submitted)
                continue
            excerpt = content[span["start"]:span["end"]]
        row_keys = {"row_index", "row_start", "row_end", "column_index", "column_start", "column_end", "row", "column"}
        if asset and isinstance(locator, dict) and row_keys.intersection(locator) and excerpt:
            # A real row and a real quote from a DIFFERENT row are not a valid
            # pair. Check the relationship, not just each field independently.
            row_values = (asset.get("locator") or {}).get("table_rows") or []
            selected_rows = [row for row in row_values if isinstance(row, dict)
                             and all(row.get(key) == locator[key] for key in row_keys.intersection(locator))]
            row_text = " | ".join(str(row.get("text") or row.get("content") or
                                      " | ".join(str(value) for value in row.get("cells", []))) for row in selected_rows)
            if excerpt not in row_text:
                reject("引文与所选表格行/单元格不一致", eid, submitted)
                continue
        # The caller cannot override an identity with a forged one.
        fields = ("knowledge_base_id", "document_id", "document_version", "chunk_id")
        if any(raw.get(k) is not None and str(raw[k]) != str(evidence.get(k)) for k in fields):
            reject("引用身份与证据不一致", eid, submitted)
            continue
        precise = bool(asset or locator or excerpt)
        item = {"evidence_id": eid, **{k: evidence.get(k) for k in fields},
                "precision": "asset" if asset else "locator" if locator else "quote" if excerpt else "chunk",
                "verification": "validated" if precise else "chunk_only"}
        if asset:
            item["asset_id"] = asset["asset_id"]
            item["visual_verification"] = (asset.get("hydration") or {}).get("visual_verification", "not_applicable")
        if raw.get("quote_id"):
            item["quote_id"] = raw["quote_id"]
        for key, value in (("locator", locator), ("quote", excerpt), ("text_span", span)):
            if value is not None:
                item[key] = value
        if span is not None:
            item["span_scope"] = "asset_context" if asset else "chunk_text"
            if not asset and type(evidence.get("text_start")) is int:
                item["document_text_span"] = {key: evidence["text_start"] + span[key] for key in ("start", "end")}
        if item not in accepted:
            accepted.append(item)
    linked = {item["evidence_id"] for item in accepted}
    for eid in evidence_ids:
        if eid in ledger and eid not in linked:
            row = ledger[eid]
            accepted.append({"evidence_id": eid, **{k: row.get(k) for k in
                              ("knowledge_base_id", "document_id", "document_version", "chunk_id")},
                             "precision": "chunk", "verification": "chunk_only"})
    return accepted, errors


def normalize_paragraph(state, text, evidence_ids, section_id, ordinal, evidence_links=None):
    # URLs/markers are generated from the ledger, never accepted from the LLM.
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", str(text)).strip()
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\[(?:\d+(?:[,，\-–]\s*\d+)*)\]", "", cleaned).strip()
    # Internal evidence handles belong only in structured evidence_ids. Models
    # sometimes echo them in Markdown, despite returning the same IDs correctly.
    cleaned = re.sub(r"[\[【(（]\s*(?:`?ev_[A-Za-z0-9_\-]+`?[\s,，;；]*)+[\]】)）]", "", cleaned)
    cleaned = re.sub(r"`?\bev_[A-Za-z0-9_\-]+\b`?", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    supplied_ids = evidence_ids if isinstance(evidence_ids, list) else []
    valid = [str(i) for i in supplied_ids if str(i) in state.get("evidence_ledger", {})]
    unknown = [str(i) for i in supplied_ids if str(i) not in state.get("evidence_ledger", {})]
    if unknown:
        state.setdefault("citation_errors", []).append({"section_id": section_id, "unknown_ids": unknown})
    links, link_errors = normalize_evidence_links(state, list(dict.fromkeys(valid)), evidence_links)
    return {"claim_id": stable_id("claim_", f"{section_id}:{ordinal}:{cleaned}"),
            "section_id": section_id, "claim_text": cleaned,
            "evidence_ids": list(dict.fromkeys(valid)), "verification_status": "pending",
            "evidence_links": links, "citation_precision": "precise" if links and all(link["verification"] == "validated" for link in links) else "chunk",
            "evidence_link_errors": link_errors,
            "reason": "尚未逐条核验"}


def validate_citations(state):
    ledger = state.get("evidence_ledger", {})
    errors = []
    for claim in state.get("claims", []):
        _, current_link_errors = normalize_evidence_links(state, claim.get("evidence_ids") or [], claim.get("evidence_links"))
        if claim.get("evidence_link_errors") or current_link_errors:
            errors.append({"claim_id": claim["claim_id"], "reason": "引用定位无效，需修正后核验", "status": "insufficient"})
        if not claim.get("evidence_ids"):
            errors.append({"claim_id": claim["claim_id"], "reason": "声明缺少来源", "status": "insufficient"})
        for evidence_id in claim.get("evidence_ids", []):
            if evidence_id not in ledger:
                errors.append({"claim_id": claim["claim_id"], "reason": f"引用不存在: {evidence_id}", "status": "contradicted"})
    return errors


def bibliography(state):
    rows = []
    for ref in references_from_ledger(state):
        authors = ref.get("authors") or []
        names = [str(a.get("name") or a.get("display_name") or "") if isinstance(a, dict) else str(a) for a in authors]
        author_text = ", ".join(names[:4]) + (" et al." if len(names) > 4 else "")
        doi = f" DOI: {ref['doi']}" if ref.get("doi") else ""
        title = str(ref["title"]).replace("[", "(").replace("]", ")")
        rows.append(f"{ref['id']}. {author_text}. [{title}]({ref['url']}). {ref.get('year') or '年份未标明'}.{doi}")
    return "\n\n".join(rows)


def render_science_report(state):
    stats = state.get("corpus_statistics", {})
    sources = sync_sources(state)
    count = len(sources)
    local_count = sum("local" in source.get("source_types", []) for source in sources)
    web_count = sum("web" in source.get("source_types", []) for source in sources)
    note = (f"本综述检索并按来源去重保留 **{count} 篇文献**（授权本地文档 {local_count} 篇，公开学术记录 {web_count} 篇；渠道计数可重叠，明确相同 DOI 只计一篇）。"
            "同一文档多个片段不重复计为多篇文献；本地文档的上传与原文定位不等于其结论已获验证。"
            "文献存在性/元数据核对与结论事实核验分别记录。正文按可取得的摘要或正文论证，"
            "未取得全文的文献不声称完成全文精读，不补造实验数值。")
    claims = state.get("claims", [])
    unsupported = [claim for claim in claims if claim.get("verification_status") != "supported"]
    outcome = state.get("research_outcome") or state.get("outcome") or "pending"
    verdict = state.get("review_verdict") or "not_reviewed"
    passed = outcome == "passed" and verdict == "pass" and bool(claims) and not unsupported
    quality = ("本报告已完成逐条声明及任务覆盖审核。" if passed else
               f"> ⚠️ **本报告未获全部审核通过**。状态：`{outcome}`；审核结论：`{verdict}`。"
               f"有 {len(unsupported)}/{len(claims)} 条声明尚未支持或尚未核验，不应作为已证实结论使用。")
    if state.get("stop_reason"):
        quality += "\n\n停止原因：`" + str(state["stop_reason"]) + "`。"
    if state.get("quality_review_note"):
        quality += "\n\n" + str(state["quality_review_note"])
    parts = [f"# {state['query']}\n", "<!-- research-quality-summary -->\n\n## 质量审核与交付状态\n\n" + quality,
             "## 研究范围与证据\n\n" + note]
    if state.get("evidence_assessment", {}).get("missing_questions"):
        parts.append("资料缺口：" + "；".join(state["evidence_assessment"]["missing_questions"]))
    for section in state.get("science_sections", []):
        paragraphs = []
        for claim in claims:
            if claim.get("section_id") != section["id"]:
                continue
            rendered = render_claim(state, claim)
            if claim.get("verification_status") != "supported":
                status = {"contradicted": "与证据冲突", "insufficient": "证据不足", "unverified": "未完成核验"}.get(
                    claim.get("verification_status"), "待核验")
                rendered = (f"> ⚠️ **{status}，以下为待修订内容，不是已证实结论**\n> "
                            + rendered.replace("\n", "\n> ") + "\n>\n> 原因："
                            + str(claim.get("reason") or "尚未逐条核验").replace("\n", "\n> "))
            paragraphs.append(rendered)
        parts.append(f"## {section['title']}\n\n" + "\n\n".join(paragraphs))
    if stats:
        parts.append("## 文献集统计与图谱口径\n\n"
                     f"以下统计仅描述本次检索集（{count} 篇），不代表领域全部文献。年份分布直接统计文献元数据；"
                     "文献按年份均衡取样并优先保留可读摘要，柱状图不能用于推断领域发文趋势。"
                     "方法关键词由标题/摘要的明确词项匹配获得，为可重叠标签，不等同于论文主要方法或性能排名。"
                     "图谱边分别表示文献属于本次研究集、发表年份、标题/摘要提及的方法关键词。"
                     "缺失年份或方法元数据的本地文档不补造属性，相关统计可能仅覆盖部分来源。")
        if stats.get("year_distribution"):
            parts.append("![文献年份分布](corpus_years)")
        if stats.get("method_mentions"):
            parts.append("![方法关键词分布](corpus_methods)")
        method_tags = stats.get("paper_tags", {})
        refs = {r["source_id"]: r for r in references_from_ledger(state)}
        matrix = ["|编号|文献|年份|标题/摘要方法关键词|", "|---|---|---|---|"]
        for paper in state.get("papers", []):
            ref = refs.get(paper["source_id"])
            if not ref:
                continue
            title = str(ref["title"]).replace("|", " ").replace("\n", " ")
            tags = "、".join(method_tags.get(paper["source_id"], [])) or "未匹配预设词项"
            matrix.append(f"|{ref['id']}|[{title}]({ref['url']})|{ref.get('year') or '—'}|{tags}|")
        parts.append("## 纳入文献对照表\n\n" + "\n".join(matrix))
    parts.append("## 参考文献\n\n" + bibliography(state))
    state["references"] = references_from_ledger(state)
    state["final_report"] = "\n\n".join(parts)
    return state["final_report"]
