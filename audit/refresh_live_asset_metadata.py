"""Refresh locators only while proving all existing indexed text is unchanged."""
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend/.env", override=True)
sys.path.insert(0, str(ROOT / "backend/app"))
from core.database import SessionLocal, POSTGRES_DB
from models.knowledge import Document
from service.docmind_service import DocMindService
from service.document_assets import build_provenance, chunk_text_with_offsets, persist_provenance
from service.milvus_service import get_milvus_service

assert POSTGRES_DB == "yayi_0929"
path = ROOT / "audit/science-assets-live.json"
report = json.loads(path.read_text(encoding="utf-8"))
with SessionLocal() as db:
    doc = db.query(Document).filter(Document.id == report["document_id"]).one()
    parsed = DocMindService().collect_structured_results(report["docmind_task_id"], 3000)
    assert not parsed.get("error"), parsed.get("error")
    chunks = chunk_text_with_offsets(parsed["text"], blocks=parsed["assets"])
    vectors = get_milvus_service().get_chunks_by_doc_id(report["collection_name"], str(doc.id))
    assert [row["content"] for row in chunks] == [row["content"] for row in vectors], "Index content changed; refuse metadata-only refresh"
    generated, records, warnings = build_provenance(str(doc.id), report["fixture_sha256"], parsed, chunks, doc.file_path)
    assert [row["chunk_id"] for row in records] == [row["id"] for row in vectors]
    persist_provenance(db, doc, report["collection_name"], {"document_version": report["fixture_sha256"], "assets": generated, "provenance": records})
    db.commit()
    report["metadata_refresh"] = {"index_text_unchanged": True, "chunk_ids_unchanged": True, "chunks": len(chunks), "warnings": warnings}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metadata_refresh"], ensure_ascii=False))
