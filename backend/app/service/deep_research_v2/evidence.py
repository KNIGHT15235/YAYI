"""Stable source/evidence identities and server-rendered scientific citations."""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse


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
                    re.sub(r"\W+", "", str(prior.get("title", "")).casefold()) == title_key):
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
        "chunk_id": row.get("chunk_id"), "asset_ids": row.get("asset_ids", []),
        "title": row.get("title"), "url": url, "doi": row.get("doi"),
        "year": row.get("year"), "authors": row.get("authors") or [],
        "content": content, "abstract": str(row.get("abstract") or ""),
        "locator": locator, "locators": row.get("locators") or [], "assets": row.get("assets") or [],
        "download_url": row.get("download_url"), "document_version": row.get("document_version"),
        "provider": row.get("provider") or ("local" if local else "web"),
        "verified": bool(row.get("verified")), "verification": row.get("verification"),
        "evidence_level": row.get("evidence_level") or ("local_text" if local else "abstract" if content else "metadata"),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "document_type": row.get("document_type") or "article",
        "retrieved_at": row.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
    }
    previous = state["evidence_ledger"].get(evidence_id)
    if previous:
        levels = {"metadata": 0, "abstract": 1, "local_text": 2, "full_text": 3}
        old_strength = (levels.get(previous.get("evidence_level"), 1), len(previous.get("content", "")))
        new_strength = (levels.get(evidence.get("evidence_level"), 1), len(content))
        # Keep text, its declared evidence level and provenance together. A
        # later metadata-only match must never relabel an acquired abstract.
        if old_strength > new_strength:
            for field in ("content", "content_hash", "abstract", "evidence_level", "locator", "locators",
                          "verification", "provider", "assets", "asset_ids", "download_url", "document_version"):
                evidence[field] = previous.get(field)
        for field in ("doi", "year", "authors", "url"):
            if not evidence.get(field):
                evidence[field] = previous.get(field)
        evidence["verified"] = bool(evidence["verified"] or previous.get("verified"))
        evidence["retrieved_at"] = previous.get("retrieved_at") or evidence["retrieved_at"]
    state["evidence_ledger"][evidence_id] = evidence
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
                       re.sub(r"\W+", "", str(p.get("title", "")).casefold()) == title_key
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
    state["papers"] = sorted(existing.values(), key=lambda p: (int(p.get("year") or 0), p["title"]))
    return {"added": added, "upgraded": upgraded}


def references_from_ledger(state):
    seen = set()
    result = []
    for evidence in state.get("evidence_ledger", {}).values():
        if evidence["source_id"] in seen:
            continue
        seen.add(evidence["source_id"])
        result.append({**evidence, "id": len(result) + 1, "source": evidence["title"],
                       "title": evidence["title"], "link": evidence["url"],
                       "marker": f"[{len(result) + 1}]"})
    return result


def citation_numbers(state):
    return {r["source_id"]: r["id"] for r in references_from_ledger(state)}


def render_claim(state, claim):
    numbers = citation_numbers(state)
    ledger = state.get("evidence_ledger", {})
    links = []
    for evidence_id in dict.fromkeys(claim.get("evidence_ids", [])):
        row = ledger.get(evidence_id)
        if row:
            links.append(f"[{numbers[row['source_id']]}]({row['url']})")
    return claim["claim_text"].strip() + (" " + " ".join(links) if links else "")


def normalize_paragraph(state, text, evidence_ids, section_id, ordinal):
    # URLs/markers are generated from the ledger, never accepted from the LLM.
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", str(text)).strip()
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\[(?:\d+(?:[,，\-–]\s*\d+)*)\]", "", cleaned).strip()
    # Internal evidence handles belong only in structured evidence_ids. Models
    # sometimes echo them in Markdown, despite returning the same IDs correctly.
    cleaned = re.sub(r"[\[【(（]\s*(?:`?ev_[A-Za-z0-9_\-]+`?[\s,，;；]*)+[\]】)）]", "", cleaned)
    cleaned = re.sub(r"`?\bev_[A-Za-z0-9_\-]+\b`?", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    valid = [str(i) for i in (evidence_ids or []) if str(i) in state.get("evidence_ledger", {})]
    unknown = [str(i) for i in (evidence_ids or []) if str(i) not in state.get("evidence_ledger", {})]
    if unknown:
        state.setdefault("citation_errors", []).append({"section_id": section_id, "unknown_ids": unknown})
    return {"claim_id": stable_id("claim_", f"{section_id}:{ordinal}:{cleaned}"),
            "section_id": section_id, "claim_text": cleaned,
            "evidence_ids": list(dict.fromkeys(valid)), "verification_status": "pending",
            "reason": "尚未逐条核验"}


def validate_citations(state):
    ledger = state.get("evidence_ledger", {})
    errors = []
    for claim in state.get("claims", []):
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
    count = len(state.get("papers", []))
    note = (f"本综述检索并去重保留 **{count} 篇文献**。来源为公开可核查的学术记录；"
            "文献存在性/元数据核对与结论事实核验分别记录。正文按可取得的摘要或正文论证，"
            "未取得全文的文献不声称完成全文精读，不补造实验数值。")
    parts = [f"# {state['query']}\n", "## 研究范围与证据\n\n" + note]
    if state.get("evidence_assessment", {}).get("missing_questions"):
        parts.append("资料缺口：" + "；".join(state["evidence_assessment"]["missing_questions"]))
    for section in state.get("science_sections", []):
        paragraphs = [render_claim(state, c) for c in state.get("claims", []) if c.get("section_id") == section["id"]]
        parts.append(f"## {section['title']}\n\n" + "\n\n".join(paragraphs))
    if stats:
        parts.append("## 文献集统计与图谱口径\n\n"
                     f"以下统计仅描述本次检索集（{count} 篇），不代表领域全部文献。年份分布直接统计文献元数据；"
                     "文献按年份均衡取样并优先保留可读摘要，柱状图不能用于推断领域发文趋势。"
                     "方法关键词由标题/摘要的明确词项匹配获得，为可重叠标签，不等同于论文主要方法或性能排名。"
                     "图谱边分别表示文献属于本次研究集、发表年份、标题/摘要提及的方法关键词。\n\n"
                     "![文献年份分布](corpus_years)\n\n![方法关键词分布](corpus_methods)")
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
