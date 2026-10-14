"""One-session AI independent evidence adjudication; default is file-only dry-run.

No LLM calls, no report/claim changes. --apply updates checkpoint and latest
assistant metadata atomically, preserving original values and audit snapshots.
It avoids POST /messages because that endpoint schedules automatic LLM memory.
"""
import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "audit"
SESSION = "164f6c9b-5eb2-400f-83d4-cb3f0b169997"
ORIGIN = "independent_evidence_review"
FILES = ("demo-result.json", "demo-checkpoint.json", "demo-history.json")
EVIDENCE = {
    "ev_118d314f8ca40ebb": (2024, "不完全监督研究尚需深入，不提供总体性能落后结论", "context_for_motivation"),
    "ev_1a4d1f0986c34745": (2025, "DA-AT指出标注成本与有限标签下的研究动机", "supports_motivation"),
    "ev_b4241846e31fcc3b": (2022, "SemiSANet指出制作变化图的人工与时间成本", "supports_motivation"),
    "ev_4ec21d278edd47b9": (2024, "MSFG-SemiCD讨论有限标注下低质量伪标签的影响", "supports_specific_limitation"),
    "ev_6e5d259fae971b72": (2022, "SemiCD报告仅使用10%标注训练数据即可接近监督性能", "counterexample_to_generalization"),
}
REASON = (
    "独立证据复核：降低标注成本是弱、半、无监督研究的重要动机，得到2024年综述、2025年DA-AT和2022年SemiSANet等摘要支持；"
    "2024年MSFG-SemiCD另指出有限标注下低质量伪标签会影响结果。但这些证据没有证明此类方法在复杂场景中通常或显著落后于全监督方法。"
    "2022年SemiCD反而报告仅使用10%的标注训练数据即可接近监督性能，该结果不能支持普遍显著落后的概括。"
    "因此，动机子命题有证据，整体假设中的比较性性能子命题证据不足，整体判为insufficient；证据不足不等于证伪。"
    "本裁决来自AI独立证据复核，不是模型自动审核结果或人类审核。"
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(value):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hyp2(container):
    values = [h for h in container["hypotheses"] if h.get("id") == "hyp_2"]
    assert len(values) == 1, "Expected exactly one hyp_2"
    return values[0]


def latest(history):
    return [m for m in history["messages"] if m["role"] == "assistant"][-1]


def replace_hypothesis(container, revised, record):
    container["hypotheses"] = [copy.deepcopy(revised) if h.get("id") == "hyp_2" else h for h in container["hypotheses"]]
    container.setdefault("independent_evidence_reviews", []).append(copy.deepcopy(record))


def prepare(documents, timestamp):
    result, checkpoint, history = [documents[name] for name in FILES]
    cp = checkpoint["checkpoint"]
    state, ui = cp["state_json"], cp["ui_state_json"]
    message = latest(history)
    science = message["references_data"]["science_data"]
    assert cp["session_id"] == history["id"] == SESSION, "Wrong session"
    assert cp["status"] == state["phase"] == "completed", "Research must be stopped"
    assert len(result["claims"]) == 29 and result["claims"] == state["claims"] == science["claims"]
    assert result["final_report"] == state["final_report"] == cp["final_report"] == message["content"]
    original = copy.deepcopy(hyp2(state))
    assert original == hyp2(result) == hyp2(ui) == hyp2(science), "Hypothesis snapshots differ"
    assert original.get("review_origin") != ORIGIN, "Already adjudicated; do not apply twice"
    assert original["status"] == "supported", "Unexpected prior hypothesis state"
    assert "显著落后" in original["content"], "Unexpected hypothesis content"
    ledger = state["evidence_ledger"]
    for eid, (year, _, _) in EVIDENCE.items():
        assert eid in ledger and ledger[eid]["year"] == year, f"Evidence missing/year changed: {eid}"
    semi = ledger["ev_6e5d259fae971b72"]["content"]
    assert "10%" in semi and "closer to the performance of supervised" in semi, "Counterexample text changed"
    review_id = "independent_hyp2_" + digest({"session": SESSION, "before": original, "reason": REASON})[:16]
    record = {
        "review_id": review_id, "review_origin": ORIGIN, "reviewer_type": "ai_assistant",
        "reviewer_label": "AI独立证据复核", "reviewed_at": timestamp, "hypothesis_id": "hyp_2",
        "previous_status": original["status"], "verdict": "insufficient", "reason": REASON,
        "evidence_ids": list(EVIDENCE), "model_rerun": False, "human_review": False,
        "report_sha256": digest(result["final_report"]), "claims_sha256": digest(result["claims"]),
        "previous_hypothesis_sha256": digest(original), "previous_message_id": message["id"],
    }
    revised = copy.deepcopy(original)
    revised.update(status="insufficient", reason=REASON, review_origin=ORIGIN,
                   model_original=original, independent_review=copy.deepcopy(record),
                   evidence=list(EVIDENCE), evidence_ids=list(EVIDENCE))
    revised["evidence_checks"] = [
        {"evidence_id": eid, "year": year, "method": description, "relation": relation,
         "supports_whole_hypothesis": False,
         "subclaim": "annotation_cost_motivation" if relation in ("context_for_motivation", "supports_motivation")
         else "limited_label_pseudo_label_quality" if relation == "supports_specific_limitation" else "performance_generalization",
         "review_origin": ORIGIN}
        for eid, (year, description, relation) in EVIDENCE.items()
    ]
    revised["subclaims"] = [
        {"id": "annotation_cost_motivation", "status": "supported", "evidence_ids": list(EVIDENCE)[:3]},
        {"id": "performance_generalization", "status": "insufficient", "evidence_ids": list(EVIDENCE),
         "reason": "已有摘要不能建立复杂场景下通常或显著落后全监督的整体比较结论；不足不等于证伪。"},
    ]
    proposed = copy.deepcopy(documents)
    replace_hypothesis(proposed[FILES[0]], revised, record)
    revised_cp = proposed[FILES[1]]["checkpoint"]
    replace_hypothesis(revised_cp["state_json"], revised, record)
    replace_hypothesis(revised_cp["ui_state_json"], revised, record)
    revised_message = latest(proposed[FILES[2]])
    replace_hypothesis(revised_message["references_data"]["science_data"], revised, record)
    revised_message["references_data"]["metadata_revision"] = copy.deepcopy(record)
    assert revised["content"] == original["content"]
    for name in FILES:
        before = copy.deepcopy(documents[name])
        after = copy.deepcopy(proposed[name])
        # Everything outside the explicitly reviewed metadata must be identical.
        if name == FILES[0]:
            containers = [(before, after)]
        elif name == FILES[1]:
            containers = [(before["checkpoint"][k], after["checkpoint"][k]) for k in ("state_json", "ui_state_json")]
        else:
            bmsg, amsg = latest(before), latest(after)
            containers = [(bmsg["references_data"]["science_data"], amsg["references_data"]["science_data"])]
            amsg["references_data"].pop("metadata_revision", None)
        for b, a in containers:
            a["hypotheses"] = copy.deepcopy(b["hypotheses"])
            a.pop("independent_evidence_reviews", None)
        assert after == before, f"Unexpected out-of-scope mutation: {name}"
    return proposed, record


def apply_database(before, proposed, record):
    """Atomic metadata-only maintenance; no automatic chat-memory work is queued."""
    sys.path.insert(0, str(ROOT / "backend" / "app"))
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=True)
    import os
    assert os.getenv('POSTGRES_DB') == 'yayi_0929' and os.getenv('POSTGRES_PORT') == '15432', 'Expected isolated YAYI database'
    from uuid import UUID
    from core.database import SessionLocal
    from models.chat import ChatSession, ChatMessage
    from models.research import ResearchCheckpoint
    from service.checkpoint_service import CheckpointService
    cp_before = before[FILES[1]]["checkpoint"]
    message_before = latest(before[FILES[2]])
    cp_after = proposed[FILES[1]]["checkpoint"]
    message_after = latest(proposed[FILES[2]])
    with SessionLocal() as db:
        with db.begin():
            session = db.query(ChatSession).filter(ChatSession.id == UUID(SESSION)).with_for_update().one()
            checkpoint = db.query(ResearchCheckpoint).filter(ResearchCheckpoint.session_id == SESSION).with_for_update().one()
            message = db.query(ChatMessage).filter(ChatMessage.session_id == session.id, ChatMessage.role == "assistant").order_by(ChatMessage.created_at.desc()).with_for_update().first()
            assert str(session.user_id) == str(checkpoint.user_id) == cp_before["user_id"], "Owner mismatch"
            assert checkpoint.status == "completed" and str(message.id) == message_before["id"]
            assert checkpoint.state_json == cp_before["state_json"], "Live checkpoint changed since snapshot"
            assert checkpoint.ui_state_json == cp_before["ui_state_json"], "Live UI snapshot changed"
            assert message.content == message_before["content"] and message.references_data == message_before["references_data"], "Live latest message changed"
            checkpoint.state_json = CheckpointService._clean_state_for_storage(CheckpointService(), cp_after["state_json"])
            checkpoint.ui_state_json = copy.deepcopy(cp_after["ui_state_json"])
            message.references_data = copy.deepcopy(message_after["references_data"])
            # Keep report text, phase, score, iteration, claim verdicts and all
            # earlier messages intact; only metadata and modification time change.
            checkpoint.updated_at = session.updated_at = datetime.utcnow()
        fresh = CheckpointService().load_full_checkpoint(SESSION, user_id=cp_before["user_id"])
        assert hyp2(fresh["state_json"])["independent_review"]["review_id"] == record["review_id"]
    # Read the public contracts after the transaction, without posting any new
    # message (POST schedules memory generation).
    from demo_access import client
    api, _ = client()
    response = api.get(f"/research/checkpoint/{SESSION}/full")
    response.raise_for_status()
    proposed[FILES[1]] = response.json()
    response = api.get(f"/sessions/{SESSION}")
    response.raise_for_status()
    proposed[FILES[2]] = response.json()
    api.close()
    state = proposed[FILES[1]]["checkpoint"]["state_json"]
    ui = proposed[FILES[1]]["checkpoint"]["ui_state_json"]
    message = latest(proposed[FILES[2]])
    assert hyp2(state) == hyp2(ui) == hyp2(proposed[FILES[0]]) == hyp2(message["references_data"]["science_data"])
    assert state["claims"] == before[FILES[0]]["claims"] == message["references_data"]["science_data"]["claims"]
    assert state["final_report"] == before[FILES[0]]["final_report"] == message["content"]
    assert state["claim_verification"] == before[FILES[0]]["claim_verification"]
    assert state["iteration"] == cp_before["state_json"]["iteration"]
    assert proposed[FILES[2]]["message_count"] == before[FILES[2]]["message_count"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the exact metadata adjudication after dry-run review")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    before = {name: read(OUT / name) for name in FILES}
    proposed, record = prepare(before, now.isoformat())
    folder = OUT / "hyp2-independent-evidence-review" / (now.strftime("%Y%m%dT%H%M%S%fZ") + ("-apply" if args.apply else "-dry-run"))
    folder.mkdir(parents=True, exist_ok=False)
    for name in FILES:
        write(folder / ("before-" + name), before[name])
        write(folder / ("proposed-" + name), proposed[name])
    ledger = before[FILES[1]]["checkpoint"]["state_json"]["evidence_ledger"]
    write(folder / "evidence.json", {eid: ledger[eid] for eid in EVIDENCE})
    write(folder / "adjudication.json", record)
    if args.apply:
        apply_database(before, proposed, record)
        for name in FILES:
            temporary = OUT / (name + ".adjudication.tmp")
            write(temporary, proposed[name])
            temporary.replace(OUT / name)
            write(folder / ("after-" + name), proposed[name])
        report = OUT / "demo-report.md"
        if report.exists():
            # Portable Markdown can have local figure/PDF links rewritten by
            # export_demo_figures; the application report was checked above.
            assert proposed[FILES[0]]["final_report"] == before[FILES[0]]["final_report"]
    summary = {"mode": "applied" if args.apply else "dry-run", "session_id": SESSION,
               "review_id": record["review_id"], "review_origin": ORIGIN, "reviewer_type": "ai_assistant",
               "hypothesis": "hyp_2", "before": "supported", "after": "insufficient",
               "report_unchanged": True, "claims_unchanged": 29, "model_calls": 0,
               "audit_directory": str(folder), "recorded_at": now.isoformat()}
    write(OUT / ("hyp2-independent-evidence-review.json" if args.apply else "hyp2-independent-evidence-review-dry-run.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
