"""Explicit two-request, public, read-only query-boundary acceptance.

No application/env loading, credentials, research, models, or literature caches.
Use --execute only with authorization for one Crossref and one arXiv HTTP request.
"""
import argparse
import asyncio
import importlib.util
import json
import xml.etree.ElementTree as ET

import httpx

from live_acceptance import ROOT, RUNTIME
from live_acceptance_api import now, read_json, write_private_json

RESULT = RUNTIME / "provider-query-acceptance.json"
PUBLIC_QUERY = "biomedical retrieval Recall@20 2024 2025"
SYNTHETIC_IDS = ("ev_7886a6bd42fc299b", "claim_e67b6c6cdc1b4ea9", "c65524f1-41f5-41d2-8461-0834c922fae7")
ENDPOINTS = {"Crossref": "https://api.crossref.org/works", "arXiv": "https://export.arxiv.org/api/query"}


class ProbeLimitReached(RuntimeError):
    pass


def load_pure_sources():
    path = ROOT / "backend/app/service/deep_research_v2/literature_sources.py"
    spec = importlib.util.spec_from_file_location("provider_query_audit_sources", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OneRequestProvider:
    def __init__(self, client, provider):
        self.client, self.provider = client, provider
        self.summary = {"provider": provider, "http_requests": 0, "status": None,
                        "result_count": None, "provider_record_count": None, "error_type": None}

    async def get(self, url, *, params):
        if self.summary["http_requests"] or url != ENDPOINTS[self.provider]:
            raise ProbeLimitReached("Read-only provider limit enforced before network access")
        params = dict(params)
        limit_key = "rows" if self.provider == "Crossref" else "max_results"
        query_key = "query.bibliographic" if self.provider == "Crossref" else "search_query"
        params[limit_key] = 1
        public_query = params[query_key]
        clean = all(internal not in public_query for internal in SYNTHETIC_IDS)
        self.summary.update(query=public_query, internal_ids_absent=clean, result_limit=1)
        if not clean:
            raise AssertionError("Internal query ID reached provider boundary")
        self.summary["http_requests"] += 1
        response = await self.client.get(url, params=params)
        self.summary["status"] = response.status_code
        if response.status_code == 200:
            if self.provider == "Crossref":
                self.summary["provider_record_count"] = len(response.json().get("message", {}).get("items", []))
            else:
                root = ET.fromstring(response.content)
                self.summary["provider_record_count"] = len(root.findall("{http://www.w3.org/2005/Atom}entry"))
        return response


async def collect():
    sources = load_pure_sources()
    scope = sources.query_scope(PUBLIC_QUERY)
    contaminated = PUBLIC_QUERY + " " + " ".join(SYNTHETIC_IDS)
    terms = [{"search_queries": [contaminated], "reason": "synthetic diagnostic, not a bibliographic query"}]
    actual = sources.targeted_searches(scope, terms)
    assert len(actual) == 1 and actual[0] == PUBLIC_QUERY
    report = {"observed_at": now(), "public_query": PUBLIC_QUERY,
              "request_limit_per_provider": 1, "result_limit_per_request": 1,
              "redirects": False, "transport_retries": 0,
              "research_calls": 0, "model_calls": 0, "literature_cache_writes": 0,
              "providers": []}
    transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
    async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(25, connect=10),
                                follow_redirects=False, trust_env=False,
                                headers={"User-Agent": "YAYI-Query-Boundary-Acceptance/1.0"}) as client:
        for name in ENDPOINTS:
            limited = OneRequestProvider(client, name)
            try:
                if name == "Crossref":
                    params = {"query.bibliographic": actual[0],
                              "filter": f"from-pub-date:{scope['start_year']}-01-01,until-pub-date:{scope['until']}",
                              "rows": 1, "sort": "relevance"}
                    rows = await sources._request(limited, params)
                else:
                    rows = await sources._arxiv(limited, scope, search_terms=terms)
                limited.summary["result_count"] = len(rows)
            except Exception as error:
                # No request/response dumps: only the exception class is retained.
                limited.summary["error_type"] = type(error).__name__
            report["providers"].append(limited.summary)
    report["boundary_passed"] = all(row["http_requests"] == 1 and row.get("internal_ids_absent")
                                    for row in report["providers"])
    report["providers_responded_200"] = all(row["status"] == 200 for row in report["providers"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    if not parser.parse_args().execute:
        parser.error("No HTTP request made; --execute requires explicit live-query authorization")
    report = asyncio.run(collect())
    previous = read_json(RESULT, {"schema_version": 1, "samples": []})
    previous.setdefault("samples", []).append(report)
    previous["latest"] = report
    write_private_json(RESULT, previous)
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["boundary_passed"] and report["providers_responded_200"] else 1)


if __name__ == "__main__":
    main()
