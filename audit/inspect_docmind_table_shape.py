"""Inspect only non-secret table-cell shape from the existing parsing job."""
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend/.env", override=True)
sys.path.insert(0, str(ROOT / "backend/app"))
from service.docmind_service import DocMindService
report = json.loads((ROOT / "audit/science-assets-live.json").read_text(encoding="utf-8"))
service = DocMindService()
value = service._result_payload(service.get_result(report["docmind_task_id"], 0, 3000))
layouts = service._result_value(value, "layouts", "Layouts")
table = next(row for row in layouts if row.get("type") == "table")
print(json.dumps({"table_keys": list(table), "first_cell": table.get("cells", [{}])[0],
                  "last_cell": table.get("cells", [{}])[-1]}, ensure_ascii=False))
