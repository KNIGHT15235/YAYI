"""Disposable, synthetic data for the browser smoke test; no browser automation."""
import argparse
import json
import secrets
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "audit" / "ui-fixture-metadata.json"
sys.path.insert(0, str(ROOT / "backend" / "app"))
load_dotenv(ROOT / "backend" / ".env")


def write_meta(data):
    META.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def request(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def setup():
    if META.exists() and not json.loads(META.read_text()).get("cleaned"):
        raise RuntimeError("An active UI fixture already exists; clean it first.")
    suffix = uuid.uuid4().hex[:12]
    username = "ui_smoke_" + suffix
    password = secrets.token_urlsafe(18)
    meta = {"fixture": "alignment_ui_smoke", "username": username, "kb_name": username,
            "sessions": [], "cleaned": False}
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as client:
        result = request(client, "POST", "/auth/register", json={"username": username,
                         "email": username + "@example.com", "password": password})
        meta["user_id"] = result["user"]["id"]
        write_meta(meta)
        client.headers["Authorization"] = "Bearer " + result["access_token"]
        # Only the newly generated, disposable account password is emitted.
        print(json.dumps({"temporary_username": username, "temporary_password": password}, ensure_ascii=False), flush=True)
        kb = request(client, "POST", "/knowledge-bases", json={"name": username, "description": "一次性 UI 冒烟合成文档，请勿用于真实研究"})
        meta["kb_id"] = kb["id"]
        write_meta(meta)
        text = "UI 冒烟合成资料。紫藤73项目在2024年的测试收入为42个单位，2025年为55个单位。该数据只用于验证知识库检索、相似度展示和原文件下载，不代表实际商业数据。"
        doc = request(client, "POST", f"/knowledge-bases/{kb['id']}/documents",
                      files={"file": ("UI冒烟_紫藤73.txt", text.encode(), "text/plain")})
        meta["document_id"] = doc["id"]
        write_meta(meta)
        session = request(client, "POST", "/sessions", json={"title": "UI冒烟：公式、代码与恢复", "session_type": "deepsearch"})
        sid = session["id"]
        meta["sessions"].append(sid)
        meta["chat_url"] = "http://localhost:5183/chat/" + sid
        write_meta(meta)
        markdown = """## UI 冒烟：Markdown 与图表

以下内容全部为合成测试数据。

行内公式：$E=mc^2$。

$$
\\frac{a}{b}+\\sqrt{2}
$$

```python
def revenue(year):
    return 42 if year == 2024 else 55
```

| 年份 | 测试收入 |
| --- | ---: |
| 2024 | 42 |
| 2025 | 55 |

![合成收入图](ui-chart-1)
"""
        request(client, "POST", f"/sessions/{sid}/messages", json={"role": "user", "content": "请展示合成公式与代码；本会话用于只查看暂停研究入口。"})
        request(client, "POST", f"/sessions/{sid}/messages", json={"role": "assistant", "content": markdown})
        from core.database import SessionLocal
        from models import ResearchCheckpoint
        with SessionLocal() as db:
            checkpoint = ResearchCheckpoint(user_id=uuid.UUID(meta["user_id"]), session_id=sid,
                query="合成 UI 研究（仅展示，不恢复运行）", phase="writing", status="paused", iteration=1,
                state_json={"query": "合成 UI 研究", "phase": "writing"},
                ui_state_json={"research_steps": [{"type": name, "status": "pending" if name == "writing" else "completed"}
                    for name in ("planning", "searching", "analyzing", "writing")],
                    "search_results": [{"id": "ui-source-1", "title": "UI合成来源", "source": "knowledge", "snippet": text}],
                    "charts": [{"id": "ui-chart-1", "title": "合成收入图", "type": "bar", "echarts_option": {
                        "xAxis": {"type": "category", "data": ["2024", "2025"]}, "yAxis": {"type": "value"},
                        "series": [{"type": "bar", "data": [42, 55]}]}}],
                    "knowledge_graph": None, "streaming_report": markdown})
            db.add(checkpoint)
            db.commit()
            db.refresh(checkpoint)
            meta["checkpoint_id"] = str(checkpoint.id)
        for _ in range(60):
            documents = request(client, "GET", f"/knowledge-bases/{kb['id']}/documents")
            record = next(row for row in documents if row["id"] == doc["id"])
            if record["status"] in ("completed", "failed"):
                break
            time.sleep(1)
        meta["document_status"] = record["status"]
        meta["document_error"] = record.get("error_message")
        meta["document_download_available"] = record.get("download_available")
        write_meta(meta)
        print(json.dumps(meta, ensure_ascii=False), flush=True)


def verify_cleanup(meta):
    from core.database import SessionLocal
    from models import User, ChatSession, ChatMessage, KnowledgeBase, Document, LongTermMemory, ResearchCheckpoint
    from service.milvus_service import get_milvus_service
    from service.knowledge_access import collection_for_name
    from service.memory_service import MEMORY_COLLECTION_NAME
    from service.memory_jobs import memory_cache, PREFIX, SUMMARY_JOBS, INDEX_JOBS
    from pymilvus import Collection, utility
    owner_id = uuid.UUID(meta["user_id"])
    session_ids = [uuid.UUID(value) for value in meta["sessions"]]
    with SessionLocal() as db:
        counts = {
            "users": db.query(User).filter(User.id == owner_id).count(),
            "sessions": db.query(ChatSession).filter(ChatSession.user_id == owner_id).count(),
            "messages": db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids)).count(),
            "knowledge_bases": db.query(KnowledgeBase).filter(KnowledgeBase.user_id == owner_id).count(),
            "documents": db.query(Document).filter(Document.user_id == owner_id).count(),
            "memories": db.query(LongTermMemory).filter(LongTermMemory.user_id == owner_id).count(),
            "checkpoints": db.query(ResearchCheckpoint).filter(ResearchCheckpoint.user_id == owner_id).count(),
        }
    assert not any(counts.values()), counts
    get_milvus_service()
    kb_exists = utility.has_collection(collection_for_name(meta["kb_name"]))
    assert not kb_exists, "Fixture KB collection remains"
    memory_vectors = []
    if utility.has_collection(MEMORY_COLLECTION_NAME):
        memory_vectors = Collection(MEMORY_COLLECTION_NAME).query("user_id == " + json.dumps(meta["user_id"]), output_fields=["id"], consistency_level="Strong")
    assert not memory_vectors, "Fixture-owned memory vectors remain"
    cache = memory_cache()
    for sid in meta["sessions"]:
        assert not cache.exists(f"{PREFIX}:session:{sid}", f"{PREFIX}:session:{sid}:messages")
        assert cache.zscore(SUMMARY_JOBS, sid) is None
    for mid in meta.get("memory_ids", []):
        assert not cache.exists(f"{PREFIX}:index:{mid}")
        assert cache.zscore(INDEX_JOBS, mid) is None
    proof = {"cleaned": True, "fixture": meta["fixture"], "username": meta["username"],
             "postgres_remaining": counts, "milvus_kb_collection_exists": kb_exists,
             "milvus_memory_vectors_remaining": len(memory_vectors), "redis_summary_and_index_jobs_remaining": 0,
             "removed_ui_memory_count": len(meta.get("memory_ids", [])), "tracked_memory_vector_count": len(meta.get("memory_vector_ids", []))}
    (ROOT / "audit" / "ui-fixture-cleanup.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    return proof


def cleanup():
    if not META.exists():
        print("No UI fixture metadata; nothing to clean.")
        return
    meta = json.loads(META.read_text(encoding="utf-8"))
    if meta.get("cleaned"):
        verify_cleanup(meta)
        print("UI fixture already cleaned.")
        return
    if meta.get("fixture") != "alignment_ui_smoke" or not meta.get("username", "").startswith("ui_smoke_"):
        raise RuntimeError("Refusing to clean unrecognized metadata.")
    from core.database import SessionLocal
    from core.security import create_access_token
    from models import User, ResearchCheckpoint, LongTermMemory
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == uuid.UUID(meta["user_id"]), User.username == meta["username"]).one_or_none()
        if user is None:
            raise RuntimeError("Fixture user missing or mismatched; manual verification required.")
        token = create_access_token(data={"sub": str(user.id), "username": user.username})
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180, headers={"Authorization": "Bearer " + token}) as client:
            if meta.get("kb_id"):
                response = client.delete(f"/knowledge-bases/{meta['kb_id']}")
                if response.status_code != 404:
                    response.raise_for_status()
            memories = db.query(LongTermMemory).filter(LongTermMemory.user_id == user.id).all()
            meta["memory_ids"] = sorted(set(meta.get("memory_ids", [])) | {str(memory.id) for memory in memories})
            meta["memory_vector_ids"] = sorted(set(meta.get("memory_vector_ids", [])) | {vid for memory in memories for vid in (memory.milvus_ids or [])})
            write_meta(meta)
            for memory in memories:
                response = client.delete(f"/memories/{memory.id}")
                if response.status_code != 404:
                    response.raise_for_status()
            for sid in meta["sessions"]:
                response = client.delete(f"/sessions/{sid}")
                if response.status_code != 404:
                    response.raise_for_status()
        # Verify API cleanup, including memory added later through the UI.
        if meta["memory_ids"]:
            from service.memory_service import get_memory_service, MEMORY_COLLECTION_NAME
            from pymilvus import Collection
            get_memory_service().milvus
            collection = Collection(MEMORY_COLLECTION_NAME)
            # Owner-scoped cleanup also covers any vectors from an interrupted index commit.
            expr = "user_id == " + json.dumps(meta["user_id"])
            remaining_vectors = collection.query(expr, output_fields=["id"], consistency_level="Strong")
            if remaining_vectors:
                collection.delete(expr)
                collection.flush()
                assert not collection.query(expr, output_fields=["id"], consistency_level="Strong"), "Fixture memory vectors remain"
        from service.memory_jobs import memory_cache, PREFIX, SUMMARY_JOBS, INDEX_JOBS, discard_session
        cache = memory_cache()
        for sid in meta["sessions"]:
            discard_session(meta["user_id"], sid)
            assert not cache.exists(f"{PREFIX}:session:{sid}", f"{PREFIX}:session:{sid}:messages")
            assert cache.zscore(SUMMARY_JOBS, sid) is None
        for mid in meta["memory_ids"]:
            cache.zrem(INDEX_JOBS, mid)
            cache.delete(f"{PREFIX}:index:{mid}")
            assert cache.zscore(INDEX_JOBS, mid) is None
            assert not cache.exists(f"{PREFIX}:index:{mid}")
        assert db.query(LongTermMemory).filter(LongTermMemory.user_id == user.id).count() == 0
        db.query(ResearchCheckpoint).filter(ResearchCheckpoint.user_id == user.id).delete(synchronize_session=False)
        db.expire_all()
        # Exact generated UUID and username only; no unrelated user or resource rows.
        db.query(User).filter(User.id == uuid.UUID(meta["user_id"]), User.username == meta["username"]).delete(synchronize_session=False)
        db.commit()
    meta["cleaned"] = True
    write_meta(meta)
    verify_cleanup(meta)
    print(json.dumps({"cleaned": True, "username": meta["username"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("setup", "cleanup"))
    action = parser.parse_args().action
    setup() if action == "setup" else cleanup()
