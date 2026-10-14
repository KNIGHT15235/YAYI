"""Bounded live research from POST /research/stream, with synthetic owned data.

Run with yayi_b after the backend is deployed. This makes real embedding/LLM
calls, starts one new research (max_iterations=1), and never seeds a checkpoint.
--self-check checks only local assertion helpers; it makes no network/DB calls.
Results use a new timestamped file and never overwrite the earlier resume audit.
"""
import argparse
import asyncio
import base64
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import secrets
import sys
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = {"source_completeness": .3, "logical_rigor": .3, "objectivity": .2,
           "timeliness": .1, "completeness": .1}
PHASES = ["planning", "researching", "analyzing", "writing", "reviewing"]
AGENTS = {"ChiefArchitect", "DeepScout", "DataAnalyst", "CodeWizard", "LeadWriter", "CriticMaster"}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_dimensions(dimensions):
    return isinstance(dimensions, dict) and all(
        key in dimensions and number(dimensions[key]) and 1 <= dimensions[key] <= 10 for key in WEIGHTS)


def weighted_matches(dimensions, score):
    return valid_dimensions(dimensions) and number(score) and 1 <= score <= 10 and abs(
        sum(dimensions[key] * weight for key, weight in WEIGHTS.items()) - score) < .011


def chart_is_renderable(chart):
    if not isinstance(chart, dict):
        return False
    option = chart.get("echarts_option")
    if isinstance(option, dict) and isinstance(option.get("series"), list) and any(
            isinstance(series, dict) and isinstance(series.get("data"), list) and series["data"]
            for series in option["series"]):
        return True
    encoded = chart.get("image_base64")
    if isinstance(encoded, str):
        try:
            raw = base64.b64decode(encoded.split(",", 1)[-1], validate=True)
            return len(raw) > 100 and raw.startswith(b"\x89PNG\r\n\x1a\n")
        except (ValueError, TypeError):
            pass
    return False


def has_ordered_phases(actual):
    remaining = iter(actual)
    return all(any(item == required for item in remaining) for required in PHASES)


class PrerequisiteFailed(RuntimeError):
    pass


class FullPipelineAudit:
    def __init__(self, args):
        self.args = args
        self.run_id = uuid.uuid4().hex[:12]
        self.marker = "风铃合成算例" + self.run_id
        self.filename = "synthetic-three-year-revenue.txt"
        self.kb_name = "audit_full_" + self.run_id
        self.started = time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.results = []
        self.events = Counter()
        self.phases = []
        self.agents = set()
        self.accounts = []
        self.session_id = self.kb_id = self.document_id = self.user_id = None
        self.local_hits = self.owned_local_hits = self.marker_local_hits = self.web_events = 0
        self.completed = self.done = self.started_research = False
        self.final_event = None
        self.checkpoint = None
        self.clients = []
        self.source = (
            f"合成软件验收数据，项目编号：{self.marker}。以下是人为设定的虚构企业收入算例，不是真实市场事实。\n"
            "指标名称为年度收入，单位均为测试单位。\n"
            "2023年年度收入为10测试单位。\n2024年年度收入为20测试单位。\n2025年年度收入为30测试单位。\n"
            "本表含三个独立年度数据点，可以绘制年度收入折线图或柱状图，并计算相邻年度同比。\n"
            "来源：本次软件验收上传的合成TXT。没有真实企业、真实市场或第三方机构数据。\n"
        ).encode("utf-8")
        self.query = (
            f"请仅研究已选本地知识库中的“{self.marker}”合成企业年度收入算例。所有数值必须来自上传文件，"
            "不得使用网络搜索或编造市场事实。先规划三个简短章节：数据来源与三年明细、收入趋势和图表、合成数据边界。"
            "请从TXT提取2023、2024、2025年三个独立的年度收入数值数据点及单位，生成至少一张实际折线图或柱状图，"
            "计算相邻年度同比，撰写约400至700字的简短报告。明确标注这是虚构的合成软件验收算例，不代表真实市场，"
            "引用本地文件来源，不追加外部研究。请如实审核证据和报告，不要求任何指定评分。"
        )

    def check(self, name, passed, **details):
        row = {"test": name, "passed": bool(passed), **details}
        self.results.append(row)
        print(json.dumps(row, ensure_ascii=False, allow_nan=False), flush=True)
        return bool(passed)

    def require(self, name, passed, **details):
        if not self.check(name, passed, **details):
            raise PrerequisiteFailed(name)

    async def api(self, client, name, method, path, expected=200, **kwargs):
        response = await client.request(method, path, **kwargs)
        self.require(name, response.status_code == expected, http_status=response.status_code)
        return response

    async def setup(self):
        for index, client in enumerate(self.clients[:2]):
            username = f"audit_full_{self.run_id}_{index}"
            response = await self.api(client, f"register synthetic account {index}", "POST", "/auth/register", 201,
                json={"username": username, "email": username + "@example.com", "password": secrets.token_urlsafe(20)})
            self.accounts.append({"username": username, "id": None})
            client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
            profile = (await self.api(client, f"identify synthetic account {index}", "GET", "/auth/me")).json()
            self.accounts[-1]["id"] = profile["id"]
        owner, other, anonymous = self.clients
        self.user_id = self.accounts[0]["id"]
        response = await self.api(owner, "create owned research session", "POST", "/sessions", 201,
                                  json={"title": "完整研究流程合成验收", "session_type": "deepsearch"})
        self.session_id = response.json()["id"]
        await self.api(anonymous, "anonymous checkpoint rejected", "GET", f"/research/checkpoint/{self.session_id}", 401)
        await self.api(other, "other user cannot start in owned session", "POST", "/research/stream", 404,
                       json={"query": "synthetic unauthorized test", "session_id": self.session_id,
                             "version": "v2", "search_web": False, "search_local": False, "max_iterations": 1})
        prior = (await self.api(owner, "read unseeded checkpoint", "GET", f"/research/checkpoint/{self.session_id}/full")).json()
        self.require("session has no seeded checkpoint", prior.get("success") is False)
        response = await self.api(owner, "create unique owned knowledge base", "POST", "/knowledge-bases", 201,
                                  json={"name": self.kb_name, "description": "Only synthetic three-year revenue data"})
        self.kb_id = response.json()["id"]
        await self.api(other, "other user cannot search owned knowledge base", "POST", f"/knowledge-bases/{self.kb_id}/search", 404,
                       json={"query": self.marker, "rerank": False})
        response = await self.api(owner, "upload synthetic three-year TXT", "POST", f"/knowledge-bases/{self.kb_id}/documents",
                                  files={"file": (self.filename, self.source, "text/plain")})
        self.document_id = response.json()["id"]
        deadline = time.monotonic() + 120
        document = {}
        while time.monotonic() < deadline:
            response = await owner.get(f"/knowledge-bases/{self.kb_id}/documents")
            response.raise_for_status()
            document = next((row for row in response.json() if row["id"] == self.document_id), {})
            if document.get("status") in ("completed", "failed"):
                break
            await asyncio.sleep(1)
        self.require("real TXT parsing and vectorization complete", document.get("status") == "completed"
                     and document.get("chunk_count", 0) > 0,
                     status=document.get("status"), chunks=document.get("chunk_count", 0))
        response = await self.api(owner, "preflight real semantic KB search", "POST", f"/knowledge-bases/{self.kb_id}/search",
                                  json={"query": self.marker + "年度收入三年明细", "top_k": 3, "rerank": False})
        hits = response.json().get("results", [])
        self.require("semantic KB search resolves synthetic source and document", any(
            hit.get("document_id") == self.document_id and self.marker in hit.get("content", "")
            and all(str(year) in hit.get("content", "") for year in (2023, 2024, 2025)) for hit in hits), hits=len(hits))

    def observe(self, item):
        event = item.get("type", "unknown")
        self.events[event] += 1
        if item.get("agent"):
            self.agents.add(item["agent"])
        payload = item.get("content") if isinstance(item.get("content"), dict) else item
        if event == "phase":
            self.phases.append(item.get("phase"))
        if event == "search_results":
            rows = payload.get("results", [])
            if payload.get("searchType") == "web":
                self.web_events += 1
            for row in rows:
                if row.get("isLocal") is True or payload.get("searchType") == "local":
                    self.local_hits += 1
                    if row.get("url", "").startswith(f"local://kb/{self.kb_name}/"):
                        self.owned_local_hits += 1
                        if self.marker in row.get("snippet", ""):
                            self.marker_local_hits += 1
        if event == "research_complete":
            self.completed = True
            self.final_event = item
        if event in ("research_start", "phase", "research_complete", "error", "warning"):
            print(json.dumps({"event": event, "phase": item.get("phase"),
                              "elapsed_s": round(time.monotonic() - self.started, 1)}, ensure_ascii=False), flush=True)

    async def research(self):
        self.started_research = True
        async with self.clients[0].stream("POST", "/research/stream", json={
            "query": self.query, "session_id": self.session_id, "kb_name": self.kb_name,
            "version": "v2", "search_web": False, "search_local": True, "max_iterations": 1,
        }) as response:
            self.require("new research POST accepted as SSE", response.status_code == 200
                         and "text/event-stream" in response.headers.get("content-type", ""), http_status=response.status_code)
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    self.done = True
                    break
                self.observe(json.loads(value))
        self.check("fresh research start observed without resume", self.events["research_start"] == 1 and not self.events["research_resumed"])
        self.check("every pipeline phase ran in order", has_ordered_phases(self.phases), phases=self.phases)
        self.check("all six agents emitted real events", AGENTS.issubset(self.agents), agents=sorted(self.agents))
        self.check("planning generated outline", self.events["outline"] > 0)
        self.check("research retrieved this owned synthetic document", self.local_hits > 0 and self.owned_local_hits > 0
                   and self.marker_local_hits > 0, local_hits=self.local_hits, owned_hits=self.owned_local_hits,
                   marker_hits=self.marker_local_hits)
        self.check("no web search events in local-only run", self.web_events == 0, web_search_events=self.web_events)
        self.check("writing emitted sections and report", self.events["section_content"] > 0 and self.events["report_draft"] > 0)
        self.check("review event emitted", self.events["review"] > 0)
        self.check("stream completed normally without error or cancellation", self.completed and self.done
                   and not self.events["error"] and not self.events["research_cancelled"], events=dict(self.events))

    async def verify_checkpoint(self):
        owner, other, _ = self.clients
        response = await self.api(owner, "read final owned checkpoint over API", "GET", f"/research/checkpoint/{self.session_id}/full")
        api_checkpoint = response.json().get("checkpoint") or {}
        from core.database import SessionLocal
        from models.research import ResearchCheckpoint
        with SessionLocal() as db:
            row = db.query(ResearchCheckpoint).filter(ResearchCheckpoint.session_id == self.session_id,
                                                      ResearchCheckpoint.user_id == self.user_id).first()
            self.checkpoint = row.to_dict(include_state=True) if row else {}
        checkpoint = self.checkpoint
        state = checkpoint.get("state_json") or {}
        self.check("final PostgreSQL checkpoint is completed and owned", checkpoint.get("user_id") == self.user_id
                   and checkpoint.get("session_id") == self.session_id and checkpoint.get("status") == "completed"
                   and state.get("phase") == "completed")
        self.check("API and PostgreSQL checkpoint match", bool(checkpoint) and api_checkpoint.get("id") == checkpoint.get("id")
                   and api_checkpoint.get("final_report") == checkpoint.get("final_report"))
        self.check("checkpoint retains local-only configuration and one iteration budget", state.get("search_web") is False
                   and state.get("search_local") is True and state.get("kb_name") == self.kb_name and state.get("max_iterations") == 1)
        data_points = state.get("data_points") or []
        def numeric_point(point):
            value = point.get("value")
            return number(value) or isinstance(value, str) and re.fullmatch(r"\s*[+-]?\d+(?:\.\d+)?\s*", value) is not None
        self.check("retrieval produced at least three numeric data points", len([point for point in data_points if numeric_point(point)]) >= 3,
                   data_points=len(data_points))
        observed_pairs = set()
        for point in data_points:
            if numeric_point(point):
                try:
                    observed_pairs.add((int(point.get("year")), float(point["value"])))
                except (TypeError, ValueError):
                    pass
        self.check("extracted annual values match the uploaded fixture", {(2023, 10.0), (2024, 20.0), (2025, 30.0)}.issubset(observed_pairs),
                   matched_fixture_years=sum(pair in observed_pairs for pair in ((2023, 10.0), (2024, 20.0), (2025, 30.0))))
        report = checkpoint.get("final_report") or ""
        self.check("nonempty report preserves synthetic data boundary", len(report) > 100
                   and any(word in report for word in ("合成", "虚构", "测试算例")), report_chars=len(report))
        self.check("report covers the three uploaded years", all(str(year) in report for year in (2023, 2024, 2025)))
        charts = state.get("charts") or []
        self.check("analysis generated renderable chart data", any(chart_is_renderable(chart) for chart in charts),
                   chart_count=len(charts), renderable_count=sum(chart_is_renderable(chart) for chart in charts))
        self.check("chart output was streamed", self.events["chart"] + self.events["charts"] > 0)
        self.check("final SSE report and charts match persisted state", bool(self.final_event)
                   and self.final_event.get("final_report") == report
                   and self.final_event.get("charts_count") == len(charts))
        dimensions = state.get("quality_dimensions") or {}
        score = state.get("quality_score")
        safe_dimensions = {key: value if number(value) else None for key, value in dimensions.items() if key in WEIGHTS}
        self.check("all five real review dimensions are valid 1 through 10", valid_dimensions(dimensions), dimensions=safe_dimensions)
        self.check("real review score strictly equals weighted dimensions", weighted_matches(dimensions, score),
                   score=score if number(score) else None)
        self.check("review is confirmed rather than fallback or unconfirmed", state.get("quality_review_status") == "confirmed",
                   review_status=state.get("quality_review_status"))
        self.check("final SSE exposes the same verified review", bool(self.final_event)
                   and weighted_matches(self.final_event.get("quality_dimensions"), self.final_event.get("quality_score"))
                   and self.final_event.get("quality_review_status") == "confirmed"
                   and self.final_event.get("quality_score") == score)
        await self.api(other, "other user cannot read final checkpoint", "GET", f"/research/checkpoint/{self.session_id}/full", 404)
        await self.api(other, "other user cannot delete final checkpoint", "DELETE", f"/research/checkpoint/{self.session_id}", 404)

    async def workflow(self):
        await self.setup()
        await self.research()
        await self.verify_checkpoint()

    async def cleanup(self):
        owner = self.clients[0]
        if self.session_id and self.started_research and not self.completed:
            try:
                response = await owner.post(f"/research/cancel/{self.session_id}", timeout=10)
                self.check("cancel unfinished own research", response.status_code == 200, http_status=response.status_code)
            except Exception as error:
                self.check("cancel unfinished own research", False, error_type=type(error).__name__)
        if self.session_id:
            try:
                for _ in range(10):
                    response = await owner.delete(f"/research/checkpoint/{self.session_id}", timeout=5)
                    if response.status_code not in (409, 429):
                        break
                    await asyncio.sleep(1)
                self.check("cleanup own checkpoint", response.status_code == 200, http_status=response.status_code)
            except Exception as error:
                self.check("cleanup own checkpoint", False, error_type=type(error).__name__)
        for name, identifier, route in (("knowledge base and original/vector data", self.kb_id, "/knowledge-bases"),
                                         ("session", self.session_id, "/sessions")):
            if identifier:
                try:
                    response = await owner.delete(route + "/" + identifier, timeout=20)
                    self.check("cleanup own " + name, response.status_code == 204, http_status=response.status_code)
                except Exception as error:
                    self.check("cleanup own " + name, False, error_type=type(error).__name__)
        # No user-delete endpoint exists. Restrict deletion to successful test
        # registrations, using the unique name and returned ID where available.
        from core.database import SessionLocal
        from models import User
        from models.research import ResearchCheckpoint
        with SessionLocal() as db:
            for account in self.accounts:
                query = db.query(User).filter(User.username == account["username"])
                if account["id"]:
                    query = query.filter(User.id == account["id"])
                user = query.first()
                if user:
                    if self.session_id and str(user.id) == self.user_id:
                        db.query(ResearchCheckpoint).filter(ResearchCheckpoint.session_id == self.session_id,
                                                           ResearchCheckpoint.user_id == user.id).delete(synchronize_session=False)
                    db.delete(user)
                    db.commit()
                self.check("cleanup exact synthetic account", query.first() is None)

    async def run(self):
        timeout = httpx.Timeout(30, connect=10, write=30, pool=10)
        self.clients = [httpx.AsyncClient(base_url=self.args.base_url, timeout=timeout) for _ in range(3)]
        try:
            await asyncio.wait_for(self.workflow(), timeout=self.args.timeout)
        except asyncio.CancelledError:
            self.check("full pipeline was not interrupted", False)
        except Exception as error:
            # Never dump response/request objects: they can contain auth headers.
            self.check("full pipeline finished within budget", False, error_type=type(error).__name__)
        finally:
            try:
                await asyncio.wait_for(self.cleanup(), timeout=75)
            except Exception as error:
                self.check("bounded resource cleanup", False, error_type=type(error).__name__)
            for client in self.clients:
                await client.aclose()
            output = self.args.output or ROOT / "audit" / (
                "research-full-pipeline-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + self.run_id + ".json")
            passed = sum(row["passed"] for row in self.results)
            result = {"run_id": self.run_id, "started_at_utc": self.started_at,
                      "elapsed_seconds": round(time.monotonic() - self.started, 2),
                      "workflow_budget_seconds": self.args.timeout, "cleanup_budget_seconds": 75,
                      "synthetic_data_only": True, "checkpoint_seeded": False, "max_iterations": 1,
                      "resources": {"session_id": self.session_id, "kb_id": self.kb_id, "kb_name": self.kb_name},
                      "events": dict(self.events), "phase_sequence": self.phases,
                      "passed": passed, "total": len(self.results), "checks": self.results}
            with Path(output).open("x", encoding="utf-8") as target:
                json.dump(result, target, ensure_ascii=False, indent=2, allow_nan=False)
                target.write("\n")
            print(f"RESULT {passed}/{len(self.results)}; output={output}", flush=True)
        return 0 if self.results and all(row["passed"] for row in self.results) else 1


def self_check():
    good = {key: 3.0 for key in WEIGHTS}
    assert weighted_matches(good, 3.0)  # A valid low score is allowed.
    for invalid in (None, True, 0, 11, "7", float("nan"), float("inf")):
        broken = dict(good, source_completeness=invalid)
        assert not valid_dimensions(broken)
        assert not weighted_matches(broken, 3.0)
    assert not weighted_matches({}, 8)
    assert not weighted_matches(good, 8)
    assert has_ordered_phases(PHASES)
    assert not has_ordered_phases(PHASES[1:])
    assert not chart_is_renderable({"title": "no chart"})
    assert chart_is_renderable({"echarts_option": {"series": [{"data": [10, 20, 30]}]}})
    print("Self-check passed: strict score, phase, and chart assertions; no network/DB calls.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=600, help="Whole workflow budget; cleanup has a separate 75-second limit")
    parser.add_argument("--output", type=Path, help="New file only; default is a unique timestamped file in audit/")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    if args.timeout < 60 or args.timeout > 1200:
        parser.error("--timeout must be between 60 and 1200 seconds")
    if args.output and (args.output.exists() or not args.output.parent.is_dir()):
        parser.error("--output must be a new file in an existing directory")
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
    sys.path.insert(0, str(ROOT / "backend" / "app"))
    return asyncio.run(FullPipelineAudit(args).run())


if __name__ == "__main__":
    raise SystemExit(main())
