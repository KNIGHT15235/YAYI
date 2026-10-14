"""Live authenticated knowledge/asset acceptance. Keeps the demonstration data."""
import argparse
import hashlib
import json
import sys
import time
import secrets
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from demo_access import client, BASE

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "audit/science-assets-live.json"
FIXTURE = ROOT / "audit/fixtures/BIT-2103.00208.pdf"


def save(report):
    report["updated_at"] = datetime.now(timezone.utc).isoformat()
    def locator(value):
        return {key: item for key, item in value.items() if key != "table_rows"}
    def asset(value):
        return {**{key: item for key, item in value.items() if key not in {"content", "locator"}},
                "content": (value.get("content") or "")[:200], "locator": locator(value.get("locator", {}))}
    def hit(value):
        return {**{key: item for key, item in value.items() if key not in {"content", "locators", "assets"}},
                "content": (value.get("content") or "")[:300],
                "locator_count": value.get("locator_count", len(value.get("locators", []))),
                "locators": [locator(row) for row in value.get("locators", [])[:2]],
                "assets": [asset(row) for row in value.get("assets", [])[:2]]}
    compact = dict(report)
    compact["assets"] = [asset(row) for row in report.get("assets", [])]
    compact["chunk_samples"] = [hit(row) for row in report.get("chunk_samples", [])[:1]]
    compact["searches"] = [{**search, "results": [hit(row) for row in search.get("results", [])[:3]]} for search in report.get("searches", [])]
    compact["report_scope"] = "Summary with bounded samples; not a complete response dump."
    temporary = REPORT.with_suffix(".tmp")
    temporary.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(REPORT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "poll", "verify"])
    args = parser.parse_args()
    c, _ = client()
    report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    if args.action == "start":
        r = c.get("/knowledge-bases")
        r.raise_for_status()
        kb = next((row for row in r.json() if row["name"] == "遥感变化检测论文"), None)
        if kb is None:
            r = c.post("/knowledge-bases", json={"name": "遥感变化检测论文", "description": "作者公开论文：Remote Sensing Image Change Detection with Transformers (BIT), arXiv:2103.00208。用于科研检索、证据定位与资产回查演示。"})
            r.raise_for_status()
            kb = r.json()
        report.update(knowledge_base_id=kb["id"], knowledge_base_name=kb["name"], fixture=FIXTURE.name,
                      fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), source_url="https://arxiv.org/abs/2103.00208",
                      backend=BASE, external_services="real DocMind, Embedding and Rerank; no mocked calls", data_retained=True)
        existing = c.get(f"/knowledge-bases/{kb['id']}/documents").json()
        document = next((row for row in existing if row["filename"] == FIXTURE.name), None)
        if document is None:
            with FIXTURE.open("rb") as source:
                r = c.post(f"/knowledge-bases/{kb['id']}/documents", files={"file": (FIXTURE.name, source, "application/pdf")})
            r.raise_for_status()
            document = r.json()
        report["document_id"] = document["id"]
        report["status"] = document.get("status", document.get("process_status"))
        save(report)
        print(json.dumps({key: report[key] for key in ("knowledge_base_id", "document_id", "status")}, ensure_ascii=False))
        return
    base = f"/knowledge-bases/{report['knowledge_base_id']}/documents/{report['document_id']}"
    if args.action == "poll":
        deadline = time.monotonic() + 45
        while True:
            r = c.get(f"/knowledge-bases/{report['knowledge_base_id']}/documents")
            r.raise_for_status()
            row = next(item for item in r.json() if item["id"] == report["document_id"])
            report.update(status=row["status"], document=row)
            save(report)
            if row["status"] in {"completed", "failed"} or time.monotonic() >= deadline:
                print(json.dumps({"status": row["status"], "chunks": row["chunk_count"], "error": row.get("error_message")}, ensure_ascii=False))
                return
            time.sleep(5)
    if report.get("status") != "completed":
        raise SystemExit("Document is not completed; run poll first")
    downloaded = c.get(base + "/download")
    downloaded.raise_for_status()
    report["original_download"] = {"status": downloaded.status_code,
                                    "sha256_matches": hashlib.sha256(downloaded.content).hexdigest() == report["fixture_sha256"]}
    r = c.get(base + "/assets")
    r.raise_for_status()
    asset_rows = r.json()["assets"]
    report["assets"] = asset_rows
    report["assets_response_bytes"] = len(r.content)
    report["asset_counts"] = dict(Counter(row["type"] for row in asset_rows))
    report["asset_media_counts"] = dict(Counter(row["media_type"] for row in asset_rows))
    chunks = c.get(base + "/chunks")
    chunks.raise_for_status()
    report["chunk_samples"] = chunks.json()["chunks"][:3]
    report["verified_chunk_count"] = chunks.json()["chunk_count"]
    report["locator_key_counts"] = dict(Counter(key for row in chunks.json()["chunks"] for locator in row.get("locators", []) for key in locator))
    queries = ["BIT bitemporal image transformer LEVIR-CD WHU F1 IoU Table I", "semantic tokens transformer encoder decoder equation attention"]
    report["searches"] = []
    for query in queries:
        response = c.post(f"/knowledge-bases/{report['knowledge_base_id']}/search", json={"query": query, "top_k": 5, "rerank": True}, timeout=180)
        response.raise_for_status()
        search = response.json()
        search["response_bytes"] = len(response.content)
        search["largest_hit_bytes"] = max((len(json.dumps(row, ensure_ascii=False).encode()) for row in search["results"]), default=0)
        report["searches"].append(search)
    previews = ROOT / "audit/science-asset-previews"
    previews.mkdir(exist_ok=True)
    report["asset_download_checks"] = []
    for kind in ("table", "equation", "image"):
        choices = [row for row in asset_rows if row["type"] == kind]
        for asset in choices[:2]:
            response = c.get(asset["download_url"])
            response.raise_for_status()
            extension = ".png" if asset["media_type"] == "image/png" else ".json"
            path = previews / (asset["asset_id"] + extension)
            path.write_bytes(response.content)
            report["asset_download_checks"].append({"asset_id": asset["asset_id"], "type": kind,
                 "status": response.status_code, "sha256_matches": hashlib.sha256(response.content).hexdigest() == asset["content_hash"], "preview_file": str(path.relative_to(ROOT))})
    with httpx.Client(base_url=BASE, timeout=30) as anonymous:
        paths = [base + "/download", base + "/assets"]
        if asset_rows:
            paths.append(asset_rows[0]["download_url"])
        report["anonymous_denied"] = [{"path": path, "status": anonymous.get(path).status_code} for path in paths]
        identity = "asset_scope_" + uuid4().hex[:10]
        response = anonymous.post("/auth/register", json={"username": identity, "password": secrets.token_urlsafe(24), "email": identity + "@example.com"})
        response.raise_for_status()
        anonymous.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        report["cross_account_denied"] = [{"path": path, "status": anonymous.get(path).status_code} for path in paths]
    payload = json.dumps(report, ensure_ascii=False)
    report["signed_credentials_in_public_payload"] = any(marker in payload for marker in ("OSSAccessKeyId=", "security-token=", "Signature="))
    assert not report["signed_credentials_in_public_payload"]
    report["verified_without_research_call"] = True
    save(report)
    print(json.dumps({"status": report["status"], "asset_counts": report["asset_counts"], "asset_media_counts": report["asset_media_counts"],
          "locator_key_counts": report["locator_key_counts"], "reranked": [row["reranked"] for row in report["searches"]],
          "download_matches": report["original_download"]["sha256_matches"], "anonymous_status": [row["status"] for row in report["anonymous_denied"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
