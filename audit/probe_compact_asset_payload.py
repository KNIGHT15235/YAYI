"""Read-only API check that search locators no longer repeat table rows."""
import json
from datetime import datetime, timezone
from pathlib import Path

from demo_access import client


report_path = Path(__file__).with_name("science-assets-live.json")
report = json.loads(report_path.read_text(encoding="utf-8"))
connection, _ = client()
response = connection.post(
    f"/knowledge-bases/{report['knowledge_base_id']}/search",
    json={"query": "BIT bitemporal image transformer LEVIR-CD WHU F1 IoU Table I", "top_k": 5, "rerank": True},
    timeout=180,
)
response.raise_for_status()
payload = response.json()
hits = payload["results"]
assert hits, "Real search returned no results"
assert all("table_rows" not in locator for hit in hits for locator in hit.get("locators", []))
assert all("table_rows" not in asset.get("locator", {}) for hit in hits for asset in hit.get("assets", []))
assert all(len(asset.get("content") or "") <= 400 for hit in hits for asset in hit.get("assets", []))
record = {
    "tested_at": datetime.now(timezone.utc).isoformat(),
    "status": response.status_code,
    "result_count": len(hits),
    "response_bytes": len(response.content),
    "largest_hit_bytes": max(len(json.dumps(hit, ensure_ascii=False).encode()) for hit in hits),
    "reranked": payload.get("reranked"),
    "search_locators_and_assets_omit_full_table_rows": True,
    "search_asset_text_maximum": 400,
}
report["compact_search_verification"] = record
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(record))
