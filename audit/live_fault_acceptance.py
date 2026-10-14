"""Opt-in fault acceptance: real ASGI/auth/PostgreSQL/Redis, synthetic nodes.

Review before running: python audit/live_fault_acceptance.py --execute
Only this acceptance manifest's owner account and newly created sessions are used.
No real models, searches, uploads, destructive cleanup, server restart, lifespan,
or schema creation. Faults exist only in this standalone Python process.
"""
import argparse
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib
import json
import logging
import os
import re
import socket
from unittest.mock import patch
from uuid import UUID, uuid4

from live_acceptance import RUNTIME, settings
from live_acceptance_api import ACCESS, BASE, SCHEMA_VERSION, read_json, write_private_json

REPORT = RUNTIME / "fault-report.json"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class FaultAcceptance:
    def __init__(self):
        self.access = read_json(ACCESS)
        self.checks, self.sessions = [], []
        self.report = {"started_at": timestamp(), "execution_id": uuid4().hex,
                       "checks": self.checks, "sessions": self.sessions,
                       "transport": "in-process real project ASGI; no lifespan",
                       "postgres": "real transactions; injected commit exceptions roll back",
                       "redis": "real project lease/cancellation clients",
                       "agents": "synthetic nodes; no provider requests",
                       "schema_creation": "disabled in this process", "records_retained": True}

    def require(self, name, condition, **details):
        self.checks.append({"name": name, "passed": bool(condition), **details})
        if not condition:
            raise AssertionError(name)

    def validate_manifest(self):
        self.require("dedicated access manifest exists", isinstance(self.access, dict))
        run_id = self.access.get("run_id", "")
        self.require("manifest matches current acceptance scope",
                     self.access.get("schema_version") == SCHEMA_VERSION
                     and self.access.get("api_base") == BASE
                     and bool(re.fullmatch(r"20261014_[0-9a-f]{10}", run_id)))
        owner = self.access.get("accounts", {}).get("owner", {})
        expected = f"live_{run_id}_owner"
        self.require("only dedicated A owner identity selected",
                     owner.get("username") == expected and owner.get("email") == expected + "@example.com"
                     and bool(owner.get("user_id")) and bool(owner.get("password")))
        UUID(owner["user_id"])
        self.owner = owner
        self.report["run_id"] = run_id
        self.report["user_id"] = owner["user_id"]

    def save(self):
        # Keep previous executions and all their synthetic sessions, never clean up.
        existing = read_json(REPORT, {"schema_version": 1, "executions": []})
        previous = [row for row in existing.get("executions", [])
                    if row.get("execution_id") != self.report["execution_id"]]
        write_private_json(REPORT, {"schema_version": 1, "executions": previous + [self.report]})

    def network_guard(self, stack):
        """Permit only local configured PG/Redis ports; no provider/model sockets."""
        ports = set()
        for service, default in (("POSTGRES", "5432"), ("REDIS", "6379")):
            self.require(f"{service} is local for isolated fault acceptance",
                         os.getenv(service + "_HOST", "localhost") in {"localhost", "127.0.0.1", "::1"})
            ports.add(int(os.getenv(service + "_PORT", default)))
        original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex

        def allowed(address):
            return (isinstance(address, tuple) and len(address) >= 2
                    and address[0] in {"127.0.0.1", "::1", "localhost"} and address[1] in ports)

        def guarded_connect(sock, address):
            if not allowed(address):
                raise RuntimeError("Fault acceptance blocked a non-PG/Redis socket")
            return original_connect(sock, address)

        def guarded_connect_ex(sock, address):
            if not allowed(address):
                raise RuntimeError("Fault acceptance blocked a non-PG/Redis socket")
            return original_connect_ex(sock, address)

        def no_http(*args, **kwargs):
            raise RuntimeError("Fault acceptance blocked a real HTTP/provider request")

        async def no_async_http(*args, **kwargs):
            no_http()

        stack.enter_context(patch.object(socket.socket, "connect", guarded_connect))
        stack.enter_context(patch.object(socket.socket, "connect_ex", guarded_connect_ex))
        import httpx
        import requests
        stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", no_http))
        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", no_async_http))
        stack.enter_context(patch.object(requests.Session, "request", no_http))

    async def run(self):
        self.validate_manifest()
        settings()  # Read locally for real infrastructure/auth; never serialize values.
        os.environ["NEWS_COLLECTION_ENABLED"] = "false"
        with ExitStack() as stack:
            self.network_guard(stack)
            from core.database import Base, engine, SessionLocal
            # app_main has a module-level create_all; the live schema must remain untouched.
            stack.enter_context(patch.object(Base.metadata, "create_all", return_value=None))
            from app_main import app
            import httpx
            import redis
            from service.checkpoint_service import CheckpointService
            from models.research import ResearchCheckpoint
            from service.deep_research_v2.graph import DeepResearchGraph
            from service.deep_research_v2.service import DeepResearchV2Service
            from config.research_profiles import get_research_profile
            router = importlib.import_module("router.research_router")
            checkpoint_service = CheckpointService()
            stack.enter_context(patch.object(router, "get_checkpoint_service", return_value=checkpoint_service))
            # Match ResearchLease so release assertions inspect this deployment's
            # configured Redis namespace, not an unrelated Redis database.
            lease_redis = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")), password=os.getenv("REDIS_PASSWORD") or None,
                db=int(os.getenv("REDIS_DB", "0")), socket_connect_timeout=5, socket_timeout=5)
            try:
                self.require("real Redis lease backend reachable", lease_redis.ping())
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                            base_url=BASE, follow_redirects=False, trust_env=False) as client:
                    login = await client.post("/auth/login", json={"username": self.owner["username"],
                                                                   "password": self.owner["password"]})
                    self.require("A owner authenticated through actual route", login.status_code == 200)
                    identity = login.json()
                    self.require("authenticated owner equals manifest",
                                 str(identity.get("user", {}).get("id")) == self.owner["user_id"]
                                 and identity.get("user", {}).get("username") == self.owner["username"]
                                 and bool(identity.get("access_token")))
                    client.headers["Authorization"] = "Bearer " + identity["access_token"]
                    for case in ("initial_commit", "phase_commit", "terminal_commit", "node_exception"):
                        response = await client.post("/sessions", json={
                            "title": f"FAULT {self.access['run_id']} {case} {self.report['execution_id'][:8]}",
                            "session_type": "deepsearch"})
                        self.require(case + ": dedicated session created", response.status_code == 201)
                        session_id = str(UUID(response.json()["id"]))
                        detail = {"case": case, "session_id": session_id, "agent_calls": [], "injected_commits": 0}
                        self.sessions.append(detail)
                        self.save()
                        original_save = CheckpointService.save_checkpoint

                        def save_with_fault(service, *args, **kwargs):
                            sid = kwargs.get("session_id", args[0] if args else None)
                            state = kwargs.get("state", args[1] if len(args) > 1 else {})
                            owner = kwargs.get("user_id", args[2] if len(args) > 2 else None)
                            self.require(case + ": checkpoint write is isolated", sid == session_id and owner == self.owner["user_id"])
                            fail = (case == "initial_commit" or
                                    (case == "phase_commit" and state.get("_next_step") == "researching") or
                                    (case == "terminal_commit" and kwargs.get("status", "running") == "completed"))
                            if not fail:
                                return original_save(service, *args, **kwargs)
                            # Real query/flush/commit handler/rollback; only this newly
                            # allocated checkpoint DB Session's commit is substituted.
                            db = service._get_db()
                            detail["injected_commits"] += 1
                            with patch.object(service, "_get_db", return_value=db), patch.object(
                                    db, "commit", side_effect=RuntimeError("synthetic_checkpoint_commit_failure")):
                                return original_save(service, *args, **kwargs)

                        class Node:
                            def __init__(node, name):
                                node.name = name

                            async def process(node, state):
                                detail["agent_calls"].append(node.name)
                                state["fault_fixture_partial"] = case
                                state["_message_queue"].put_nowait({"type": "thought", "content": "synthetic fault fixture"})
                                if case == "node_exception":
                                    raise RuntimeError("synthetic_model_node_failure")
                                if node.name == "writer":
                                    state["final_report"] = "Synthetic fault fixture; no research conclusions."
                                if node.name == "critic":
                                    state.update(phase="completed", research_outcome="completed_with_warnings",
                                                 outcome="completed_with_warnings", review_verdict="unconfirmed",
                                                 stop_reason="synthetic_fault_test")
                                return state

                        def synthetic_service(*args, **kwargs):
                            detail["service_started"] = True
                            graph = DeepResearchGraph.__new__(DeepResearchGraph)
                            graph.max_iterations = 1
                            graph.research_profile = get_research_profile("science", 1)
                            graph.checkpoint_service = checkpoint_service
                            for name in ("architect", "scout", "data_analyst", "wizard", "writer", "critic"):
                                setattr(graph, name, Node(name))
                            service = DeepResearchV2Service.__new__(DeepResearchV2Service)
                            service.graph = graph
                            return service

                        with patch.object(CheckpointService, "save_checkpoint", save_with_fault), patch.object(
                                router, "get_research_service_v2", side_effect=synthetic_service):
                            response = await asyncio.wait_for(client.post("/research/stream", json={
                                "query": "Synthetic failure acceptance only; no provider requests.",
                                "session_id": session_id, "search_modes": [], "version": "v2",
                                "profile_id": "science", "min_papers": 1, "max_iterations": 1}), timeout=45)
                        detail["http_status"] = response.status_code
                        with SessionLocal() as db:
                            checkpoint = db.query(ResearchCheckpoint).filter(
                                ResearchCheckpoint.session_id == session_id,
                                ResearchCheckpoint.user_id == UUID(self.owner["user_id"])).one_or_none()
                            snapshot = checkpoint.to_dict(include_state=True) if checkpoint else None
                        detail["checkpoint_status"] = snapshot.get("status") if snapshot else None
                        if case == "initial_commit":
                            self.require(case + ": HTTP 503 before stream", response.status_code == 503)
                            self.require(case + ": no agent or service started",
                                         not detail["agent_calls"] and not detail.get("service_started"))
                            self.require(case + ": failed transaction created no checkpoint", snapshot is None)
                        else:
                            self.require(case + ": SSE established", response.status_code == 200
                                         and response.headers.get("content-type", "").startswith("text/event-stream"))
                            frames = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
                            events = [json.loads(frame) for frame in frames if frame != "[DONE]"]
                            detail["events"] = [{"type": e.get("type"), "code": e.get("code"),
                                                  "checkpoint_saved": e.get("checkpoint_saved")} for e in events]
                            self.require(case + ": all events scoped to this run", bool(events) and all(
                                e.get("run_id") == e.get("session_id") == session_id for e in events))
                            self.require(case + ": terminal error, no false completion", events[-1].get("type") == "error"
                                         and not any(e.get("type") in {"research_complete", "research_cancelled"} for e in events))
                            self.require(case + ": stream terminator is not success", frames[-1] == "[DONE]")
                            self.require(case + ": real checkpoint readable and not completed",
                                         snapshot is not None and snapshot["status"] != "completed")
                            if case == "node_exception":
                                self.require(case + ": failure persisted with partial state",
                                    snapshot["status"] == "failed"
                                    and snapshot["state_json"].get("fault_fixture_partial") == case
                                    and snapshot.get("error_message") == "synthetic_model_node_failure"
                                    and detail["agent_calls"] == ["architect"])
                            else:
                                self.require(case + ": failed save truthfully reported",
                                    events[-1].get("code") == "checkpoint_persistence_failed"
                                    and events[-1].get("checkpoint_saved") is False
                                    and snapshot["status"] == "running")
                                if case == "phase_commit":
                                    self.require(case + ": failed phase cannot advance",
                                        detail["agent_calls"] == ["architect"]
                                        and snapshot["state_json"].get("_next_step") == "planning"
                                        and "fault_fixture_partial" not in snapshot["state_json"])
                                else:
                                    self.require(case + ": terminal commit was actually reached",
                                        detail["agent_calls"] == ["architect", "scout", "data_analyst", "wizard", "writer", "critic"])
                        self.require(case + ": injected fault exercised",
                                     detail["injected_commits"] > 0 if case != "node_exception" else detail["injected_commits"] == 0)
                        self.require(case + ": actual Redis lease released", not lease_redis.exists(
                            f"research:active:user:{self.owner['user_id']}", f"research:active:session:{session_id}"))
                        self.save()
            finally:
                lease_redis.close()
                engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly authorize this isolated live fault run")
    if not parser.parse_args().execute:
        parser.error("No live action taken; review the script and explicitly pass --execute")
    acceptance = FaultAcceptance()
    successful = False
    try:
        # Backend/SDK log formatting is not a security boundary: discard it. The
        # report contains only our explicit booleans, IDs, statuses and test names.
        logging.disable(logging.CRITICAL)
        with open(os.devnull, "w", encoding="utf-8") as silence, redirect_stdout(silence), redirect_stderr(silence):
            asyncio.run(acceptance.run())
        successful = True
    except Exception as error:
        acceptance.report["error_type"] = type(error).__name__
    finally:
        acceptance.report.update(success=successful, finished_at=timestamp())
        acceptance.save()
    print(json.dumps({"success": successful, "checks": len(acceptance.checks),
                      "failed_checks": [row["name"] for row in acceptance.checks if not row["passed"]],
                      "error_type": acceptance.report.get("error_type"), "report": str(REPORT)}, ensure_ascii=False))
    raise SystemExit(0 if successful else 1)


if __name__ == "__main__":
    main()
