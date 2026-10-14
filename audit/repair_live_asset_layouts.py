"""Rebuild the demo from its completed real DocMind job; no new parsing job."""
import json
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend/.env", override=True)
sys.path.insert(0, str(ROOT / "backend/app"))
from core.database import SessionLocal, POSTGRES_DB
from models.knowledge import Document, DocumentAsset
from service.docmind_service import process_document_with_docmind
from service.document_assets import persist_provenance, remove_asset_files
from service.milvus_service import get_milvus_service, normalize_collection_name
from service.knowledge_access import collection_for_name

assert POSTGRES_DB == "yayi_0929", "Refuse to modify any other database"
report_path = ROOT / "audit/science-assets-live.json"
report = json.loads(report_path.read_text(encoding="utf-8"))
with SessionLocal() as db:
    doc = db.query(Document).filter(Document.id == report["document_id"]).one()
    old_assets = db.query(DocumentAsset).filter_by(document_id=doc.id).all()
    old_paths = [asset.file_path for asset in old_assets]
    task = next((re.search(r"docmind-\d{8}-[0-9a-f]+", asset.content or "").group(0)
                 for asset in old_assets if re.search(r"docmind-\d{8}-[0-9a-f]+", asset.content or "")), report.get("docmind_task_id"))
    assert task, "No existing completed DocMind task found"
    collection = collection_for_name(doc.knowledge_base.name)
    report["docmind_task_id"] = task
    report["collection_name"] = normalize_collection_name(collection)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    doc.status = "processing"
    db.commit()
    get_milvus_service().delete_by_doc_id(collection, str(doc.id))
    result = process_document_with_docmind(doc.file_path, doc.filename, collection,
                                          document_id=str(doc.id), existing_task_id=task)
    if not result["success"]:
        doc.status, doc.error_message = "failed", result["message"]
        db.commit()
        raise RuntimeError(result["message"])
    persist_provenance(db, doc, collection, result)
    doc.status, doc.error_message, doc.chunk_count = "completed", None, result["document_count"]
    db.commit()
    new_paths = {asset["file_path"] for asset in result["assets"]}
    remove_asset_files([path for path in old_paths if path not in new_paths])
    report.update(status="completed", reused_docmind_job=True, parsing_warnings=result.get("warnings", []),
                  rebuilt_chunk_count=result["document_count"], rebuilt_asset_count=len(result["assets"]))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": doc.status, "chunks": doc.chunk_count,
                      "assets": len(result["assets"]), "warnings": result.get("warnings", []),
                      "collection_name": report["collection_name"]}, ensure_ascii=False))
