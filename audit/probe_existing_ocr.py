"""Read only the already-submitted synthetic OCR audit job; never resubmit."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env")
from service.docmind_service import DocMindService

TASK_ID = "docmind-20260921-7eb9d60c765046b597e04fb22afc6c24"
service = DocMindService()
status = service.query_status(TASK_ID)
data = service.get_result(TASK_ID)
def shape(value, depth=0):
    if hasattr(value, "to_map"):
        value = value.to_map()
    if depth > 7:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return {"length": len(value), "first_items": [shape(item, depth + 1) for item in value[:2]]}
    if isinstance(value, str):
        return {"type": "str", "length": len(value), "contains_synthetic_marker": "7342" in value}
    return value
parsed = service.collect_all_results(TASK_ID)
result = {"status": status.get("Status") if status else None, "status_shape": shape(status),
          "result_shape": shape(data), "parsed_length": len(parsed), "contains_synthetic_marker": "7342" in parsed,
          "parse_error": service.last_error, "submitted_new_job": False}
(ROOT / "audit" / "docmind_existing_ocr_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
