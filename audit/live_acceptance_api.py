"""Explicit, scoped API acceptance; no research/model task and no cleanup.

Commands: setup -> upload -> poll -> inspect -> isolation.
Upload/inspect can call real document/embedding/rerank providers through the API.
Only setup registers accounts; never reuse or modify the user's demo account.
Secrets are stored only in git-ignored RUNTIME/access.json, never in reports.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from live_acceptance import ROOT, RUNTIME, safe_error, settings


BASE = "http://127.0.0.1:8029"
ACCESS = RUNTIME / "access.json"
REPORT = RUNTIME / "report.json"
FIXTURE = ROOT / "output" / "pdf" / "yayi-live-synthetic-study.pdf"
SCHEMA_VERSION = 1
SEARCH_QUERY = "YAYI-LIVE-20261014 Table 1 Hybrid RRF Recall@20 latency p50 86.0 63"


def now():
    return datetime.now(timezone.utc).isoformat()


def write_private_json(path, value):
    """Atomic, private runtime output; never write source files or external paths."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if path.parent.resolve() != RUNTIME.resolve():
        raise ValueError("Output must be inside the dedicated acceptance runtime")
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=RUNTIME)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(value, target, ensure_ascii=False, indent=2, allow_nan=False)
            target.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class Acceptance:
    def __init__(self, command):
        self.command = command
        self.values = settings()  # Values are used solely to redact error messages.
        self.access = read_json(ACCESS)
        self.report = read_json(REPORT, {"schema_version": SCHEMA_VERSION, "api_base": BASE, "runs": []})
        self.checks = []
        self.clients = []
        self.started_at = now()

    def redact(self, value):
        values = dict(self.values)
        for role, account in (self.access or {}).get("accounts", {}).items():
            for name in ("password", "access_token"):
                values[f"{role}_{name}"] = account.get(name)
        text = safe_error(RuntimeError(str(value)), values)["message"]
        text = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[REDACTED]", text)
        text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_JWT]", text)
        text = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|secret|password|signature|security-token|OSSAccessKeyId)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'&}]+", r"\1[REDACTED]", text)
        return text[:700]

    def check(self, name, passed, **details):
        row = {"name": name, "passed": bool(passed), **details}
        self.checks.append(row)
        return bool(passed)

    def require(self, name, passed, **details):
        if not self.check(name, passed, **details):
            raise RuntimeError(name)

    def client(self):
        client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(180, connect=10),
                              follow_redirects=False, trust_env=False)
        self.clients.append(client)
        return client

    def request(self, client, name, method, path, expected=200, required=True, **kwargs):
        # Request targets must remain on this API. Never follow provider asset URLs.
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Only relative paths on the fixed local API are permitted")
        try:
            response = client.request(method, path, **kwargs)
        except Exception as error:
            self.check(name, False, method=method, path=parsed.path,
                       error_type=type(error).__name__, error=self.redact(error))
            if required:
                raise RuntimeError(name + ": request failed") from error
            return None
        details = {"method": method, "path": parsed.path, "status": response.status_code,
                   "expected_status": expected}
        if response.status_code != expected:
            try:
                message = response.json().get("detail", "Unexpected API response")
            except (ValueError, AttributeError):
                message = response.text
            details["error"] = self.redact(message)
        passed = self.check(name, response.status_code == expected, **details)
        if required and not passed:
            raise RuntimeError(f"{name}: HTTP {response.status_code}, expected {expected}")
        return response

    def validate_access(self):
        self.require("dedicated run manifest exists", isinstance(self.access, dict))
        run_id = self.access.get("run_id", "")
        self.require("manifest belongs to this acceptance scope",
                     self.access.get("schema_version") == SCHEMA_VERSION
                     and self.access.get("api_base") == BASE
                     and bool(re.fullmatch(r"20261014_[0-9a-f]{10}", run_id)))
        accounts = self.access.get("accounts", {})
        for role in ("owner", "other"):
            account = accounts.get(role, {})
            expected = f"live_{run_id}_{role}"
            self.require(f"{role} is an isolated synthetic account",
                         account.get("username") == expected
                         and account.get("email") == expected + "@example.com"
                         and bool(account.get("password")))
        self.report["run_id"] = run_id

    def authenticated(self, role):
        self.validate_access()
        account = self.access["accounts"][role]
        self.require(f"{role} was registered by setup", bool(account.get("user_id")))
        client = self.client()
        # Login permits expired-token recovery, never automatic registration.
        response = self.request(client, f"login dedicated {role}", "POST", "/auth/login",
                                json={"username": account["username"], "password": account["password"]})
        payload = response.json()
        self.require(f"{role} login identity unchanged",
                     str(payload.get("user", {}).get("id")) == account["user_id"]
                     and payload.get("user", {}).get("username") == account["username"])
        self.require(f"{role} bearer credential returned", bool(payload.get("access_token")))
        account["access_token"] = payload["access_token"]
        write_private_json(ACCESS, self.access)
        client.headers["Authorization"] = "Bearer " + account["access_token"]
        return client

    def setup(self):
        if self.access is None:
            run_id = "20261014_" + secrets.token_hex(5)
            self.access = {"schema_version": SCHEMA_VERSION, "run_id": run_id,
                           "api_base": BASE, "created_at": now(), "accounts": {}}
            for role in ("owner", "other"):
                username = f"live_{run_id}_{role}"
                self.access["accounts"][role] = {"username": username,
                    "email": username + "@example.com", "password": secrets.token_urlsafe(24)}
            # Save generated credentials before registering, so a crash cannot lose them.
            write_private_json(ACCESS, self.access)
        self.validate_access()
        for role, account in self.access["accounts"].items():
            if account.get("user_id"):
                self.authenticated(role)
                continue
            client = self.client()
            response = self.request(client, f"register dedicated {role}", "POST", "/auth/register",
                expected=201, required=False, json={key: account[key] for key in ("username", "email", "password")})
            if response is None:
                raise RuntimeError("Registration result unavailable; credentials retained for retry")
            if response.status_code == 400:
                # A prior request may have committed before its response was lost.
                # Only the just-generated account's exact credentials may recover it.
                response = self.request(client, f"recover dedicated {role} registration", "POST", "/auth/login",
                    json={"username": account["username"], "password": account["password"]})
            elif response.status_code != 201:
                raise RuntimeError(f"Registration rejected: HTTP {response.status_code}")
            payload = response.json()
            user = payload.get("user", {})
            self.require(f"{role} registered identity matches generated manifest",
                         user.get("username") == account["username"] and user.get("email") == account["email"]
                         and bool(user.get("id")) and bool(payload.get("access_token")))
            account.update(user_id=str(user["id"]), access_token=payload["access_token"])
            write_private_json(ACCESS, self.access)
        self.report["accounts"] = {role: {"user_id": account["user_id"]}
                                   for role, account in self.access["accounts"].items()}
        self.report["setup_complete"] = True

    def resources(self):
        self.validate_access()
        resources = self.report.get("resources", {})
        self.require("this run owns the knowledge base manifest",
                     resources.get("run_id") == self.access["run_id"]
                     and resources.get("knowledge_base_name") == "live_" + self.access["run_id"]
                     and bool(resources.get("knowledge_base_id")))
        return resources

    def document_base(self):
        resources = self.resources()
        self.require("this run has an uploaded document", bool(resources.get("document_id")))
        return f"/knowledge-bases/{resources['knowledge_base_id']}/documents/{resources['document_id']}"

    def upload(self):
        client = self.authenticated("owner")
        self.require("synthetic PDF fixture exists", FIXTURE.is_file())
        fixture_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        resources = self.report.get("resources")
        if not resources:
            name = "live_" + self.access["run_id"]
            response = self.request(client, "create dedicated knowledge base", "POST", "/knowledge-bases",
                expected=201, json={"name": name, "description": "2026-10-14 isolated live API acceptance; synthetic PDF only"})
            kb = response.json()
            resources = {"run_id": self.access["run_id"], "knowledge_base_id": kb["id"],
                         "knowledge_base_name": name, "fixture": str(FIXTURE.relative_to(ROOT)),
                         "fixture_sha256": fixture_hash}
            self.report["resources"] = resources
            write_private_json(REPORT, self.report)
        self.resources()
        self.require("fixture unchanged within this run", resources.get("fixture_sha256") == fixture_hash)
        if resources.get("document_id"):
            self.check("upload already recorded; no duplicate upload", True, document_id=resources["document_id"])
            return
        with FIXTURE.open("rb") as source:
            response = self.request(client, "upload synthetic PDF", "POST",
                f"/knowledge-bases/{resources['knowledge_base_id']}/documents",
                files={"file": (FIXTURE.name, source, "application/pdf")})
        payload = response.json()
        resources["document_id"] = payload["id"]
        self.report["document_status"] = payload.get("process_status")
        write_private_json(REPORT, self.report)
        self.require("upload accepted for background processing",
                     payload.get("status") == "success" and payload.get("process_status") == "pending"
                     and payload.get("filename") == FIXTURE.name,
                     api_status=payload.get("status"), process_status=payload.get("process_status"))

    def poll(self, wait_seconds, interval):
        client = self.authenticated("owner")
        self.document_base()
        resources = self.resources()
        deadline = time.monotonic() + wait_seconds
        while True:
            response = self.request(client, "poll document processing", "GET",
                                    f"/knowledge-bases/{resources['knowledge_base_id']}/documents")
            document = next((row for row in response.json() if row.get("id") == resources["document_id"]), None)
            self.require("uploaded document remains in owned knowledge base", document is not None)
            self.report["document_status"] = document["status"]
            self.report["document"] = {key: document.get(key) for key in (
                "id", "knowledge_base_id", "filename", "status", "chunk_count", "download_available")}
            if document.get("error_message"):
                self.report["document"]["error"] = self.redact(document["error_message"])
            if document["status"] in ("completed", "failed"):
                self.report["pending"] = False
                self.require("document ingestion completed with chunks",
                             document["status"] == "completed" and document.get("chunk_count", 0) > 0,
                             process_status=document["status"], chunk_count=document.get("chunk_count", 0),
                             error=self.redact(document.get("error_message") or ""))
                break
            if time.monotonic() >= deadline:
                self.report["pending"] = True
                break
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
        if document["status"] in ("completed", "failed"):
            self.report["pending"] = False

    def get_assets(self, client, base):
        payload = self.request(client, "list owned document assets", "GET", base + "/assets").json()
        assets = payload.get("assets", [])
        self.require("structured document assets exist", bool(assets))
        return assets

    def inspect(self):
        client = self.authenticated("owner")
        base = self.document_base()
        resources = self.resources()
        original = self.request(client, "download original synthetic PDF", "GET", base + "/download")
        self.check("downloaded original matches uploaded hash",
                   hashlib.sha256(original.content).hexdigest() == resources["fixture_sha256"])
        chunks = self.request(client, "retrieve persisted vector chunks", "GET", base + "/chunks").json()
        rows = chunks.get("chunks", [])
        self.check("Milvus chunks are nonempty", chunks.get("chunk_count", 0) > 0 and bool(rows))
        self.check("chunks retain document version and evidence identity",
                   bool(rows) and all(row.get("document_version") and row.get("evidence_id") for row in rows))
        self.report["chunk_summary"] = {"count": chunks.get("chunk_count", 0),
            "versions": sorted({row["document_version"] for row in rows if row.get("document_version")}),
            "locator_count": sum(len(row.get("locators") or []) for row in rows)}
        assets = self.get_assets(client, base)
        self.report["asset_summary"] = {"count": len(assets), "types": dict(Counter(row.get("type") for row in assets)),
            "assets": [{key: row.get(key) for key in ("asset_id", "document_id", "document_version", "type", "media_type", "content_hash")}
                       for row in assets]}
        selected, kinds = [], set()
        for row in assets:
            if row.get("type") not in kinds:
                kinds.add(row.get("type"))
                selected.append(row)
        for asset in selected[:4]:
            asset_base = base + "/assets/" + asset["asset_id"]
            evidence = self.request(client, "hydrate " + asset["type"] + " evidence", "GET", asset_base + "/evidence",
                params={"document_version": asset["document_version"], "query": SEARCH_QUERY, "max_chars": 5000}).json()
            self.check("asset evidence stays on exact identity/version",
                       evidence.get("asset_id") == asset["asset_id"]
                       and evidence.get("document_id") == resources["document_id"]
                       and evidence.get("document_version") == asset["document_version"])
            downloaded = self.request(client, "download " + asset["type"] + " asset", "GET", asset_base + "/download")
            self.check("asset download matches content hash",
                       hashlib.sha256(downloaded.content).hexdigest() == asset.get("content_hash"), asset_id=asset["asset_id"])
        searches = []
        for rerank in (False, True):
            payload = self.request(client, "search with rerank=" + str(rerank), "POST",
                f"/knowledge-bases/{resources['knowledge_base_id']}/search",
                json={"query": SEARCH_QUERY, "top_k": 5, "rerank": rerank}).json()
            hits = payload.get("results", [])
            self.check("search resolves only this run's uploaded document", bool(hits) and all(
                hit.get("document_id") == resources["document_id"]
                and hit.get("knowledge_base_id") == resources["knowledge_base_id"] for hit in hits), rerank_requested=rerank)
            self.check("requested rerank mode was applied", payload.get("reranked") is rerank,
                       rerank_requested=rerank, reranked=payload.get("reranked"), warning=self.redact(payload.get("warning") or ""))
            searches.append({"rerank_requested": rerank, "reranked": payload.get("reranked"),
                "hit_count": len(hits), "warning": self.redact(payload.get("warning") or ""),
                "hits": [{key: hit.get(key) for key in ("chunk_id", "document_id", "document_version", "evidence_id", "score", "rerank_score")}
                         for hit in hits]})
        self.report["searches"] = searches

    def isolation(self):
        owner, other, anonymous = self.authenticated("owner"), self.authenticated("other"), self.client()
        base = self.document_base()
        resources = self.resources()
        assets = self.get_assets(owner, base)
        asset = assets[0]
        asset_base = base + "/assets/" + asset["asset_id"]
        kb_base = f"/knowledge-bases/{resources['knowledge_base_id']}"
        paths = [kb_base, kb_base + "/documents", base + "/chunks", base + "/download", base + "/assets",
                 asset_base + "/evidence", asset_base + "/download"]
        matrix = []
        for role, client, expected in (("other", other, 404), ("anonymous", anonymous, 401)):
            for path in paths:
                kwargs = {"params": {"document_version": asset["document_version"]}} if path.endswith("/evidence") else {}
                response = self.request(client, role + " cannot read owned resource", "GET", path,
                                        expected=expected, required=False, **kwargs)
                matrix.append({"role": role, "path": path, "status": response.status_code if response is not None else None,
                               "expected_status": expected})
            # Ownership rejection must happen before vector/model requests.
            response = self.request(client, role + " cannot search owned knowledge base", "POST", kb_base + "/search",
                expected=expected, required=False, json={"query": SEARCH_QUERY, "top_k": 1, "rerank": False})
            matrix.append({"role": role, "path": kb_base + "/search", "status": response.status_code if response is not None else None,
                           "expected_status": expected})
        absent_version = "absent_" + secrets.token_hex(12)
        self.request(owner, "unknown asset version is rejected", "GET", asset_base + "/evidence", expected=404,
                     required=False, params={"document_version": absent_version})
        self.request(owner, "asset evidence requires explicit version", "GET", asset_base + "/evidence",
                     expected=422, required=False)
        response = self.request(owner, "unknown version has empty asset list", "GET", base + "/assets",
                                params={"document_version": absent_version})
        self.check("asset list does not fall back across versions", response.json().get("assets") == [])
        self.report["isolation"] = matrix

    def finish(self, error=None):
        if error is not None:
            self.check("command completed", False, error_type=type(error).__name__, error=self.redact(error))
        for client in self.clients:
            client.close()
        failed = [row for row in self.checks if not row["passed"]]
        summary = {"command": self.command, "started_at": self.started_at, "finished_at": now(),
            "passed": len(self.checks) - len(failed), "total": len(self.checks), "failed": len(failed),
            "pending": bool(self.report.get("pending")) if self.command == "poll" else False,
            "research_started": False, "data_deleted": False, "checks": self.checks}
        self.report.setdefault("runs", []).append(summary)
        self.report["updated_at"] = now()
        write_private_json(REPORT, self.report)
        print(json.dumps({key: value for key, value in summary.items() if key != "checks"}, ensure_ascii=False))
        if failed:
            print(json.dumps({"failures": failed}, ensure_ascii=False))
        return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "upload", "poll", "inspect", "isolation"))
    parser.add_argument("--wait-seconds", type=int, default=45, help="poll only; 0..300 seconds")
    parser.add_argument("--interval", type=int, default=5, help="poll only; 1..30 seconds")
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 300 or not 1 <= args.interval <= 30:
        parser.error("--wait-seconds must be 0..300 and --interval must be 1..30")
    acceptance = Acceptance(args.command)
    try:
        if args.command == "poll":
            acceptance.poll(args.wait_seconds, args.interval)
        else:
            getattr(acceptance, args.command)()
    except Exception as error:
        return acceptance.finish(error)
    return acceptance.finish()


if __name__ == "__main__":
    raise SystemExit(main())
