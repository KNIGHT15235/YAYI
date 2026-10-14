"""Remove duplicated whole-table rows from per-chunk locators only."""
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend/.env", override=True)
sys.path.insert(0, str(ROOT / "backend/app"))
from core.database import SessionLocal, POSTGRES_DB
from models.knowledge import DocumentChunkProvenance
from live_science_assets import REPORT, save

assert POSTGRES_DB == "yayi_0929"
report = json.loads(REPORT.read_text(encoding="utf-8"))
with SessionLocal() as db:
    rows = db.query(DocumentChunkProvenance).filter_by(document_id=report["document_id"]).all()
    before, after = 0, 0
    for row in rows:
        before += len(json.dumps(row.locators, ensure_ascii=False).encode())
        compact, seen = [], set()
        for locator in row.locators:
            item = {key: value for key, value in locator.items() if key != "table_rows"}
            identity = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if identity not in seen:
                compact.append(item)
                seen.add(identity)
        row.locators = compact
        after += len(json.dumps(compact, ensure_ascii=False).encode())
    db.commit()
report["locator_compaction"] = {"chunks": len(rows), "before_bytes": before, "after_bytes": after,
                                 "vector_text_and_ids_changed": False, "full_table_cells_retained_in_assets": True}
save(report)
print(json.dumps(report["locator_compaction"]))
