"""Publish the audited 120-paper corpus; default is offline validation only.

Apply explicitly: python audit/configure_database_demo.py --apply
Only these two public demo tables are created/updated. Existing account,
research history, industry data and differently owned corpus rows are untouched.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend" / "app"))
from config.research_profiles import get_research_profile
from service.database_catalog import DEMO_CORPUS_ID

TAGGING_RULE = "title_abstract_keyword_multilabel_v1"


def prepare_rows(source):
    raw = Path(source).read_bytes()
    snapshot = json.loads(raw)
    papers = snapshot.get("papers") or []
    if len(papers) != 120:
        raise ValueError("本导入仅接收已审计正式展示的120篇文献")
    saved_tags = snapshot.get("corpus_statistics", {}).get("paper_tags", {})
    method_terms = get_research_profile("science")["method_terms"]
    rows, methods, seen = [], [], set()
    for paper in papers:
        paper_id = str(paper.get("source_id") or "")
        if not paper_id or paper_id in seen:
            raise ValueError("文献标识缺失或重复")
        seen.add(paper_id)
        if not paper.get("title") or urlparse(paper.get("url") or "").scheme not in {"https", "http"}:
            raise ValueError("文献缺少题名或可追溯的网络来源")
        if paper.get("verified") is not True or paper.get("evidence_level") not in {"abstract", "metadata"}:
            raise ValueError("仅发布已核验公开元数据及公开摘要，不导入本地私有材料")
        year = int(paper.get("year") or 0)
        if not 2020 <= year <= 2026:
            raise ValueError("文献年份超出正式展示范围")
        authors = paper.get("authors") or []
        if not isinstance(authors, list) or any(not isinstance(author, str) for author in authors):
            raise ValueError("公开作者元数据格式异常")
        rows.append({"paper_id": paper_id, "title": paper["title"], "publication_year": year,
                     "authors": "; ".join(authors), "venue": paper.get("venue") or None,
                     "doi": paper.get("doi") or None, "source_url": paper["url"],
                     "metadata_source": paper.get("provider") or None,
                     "evidence_level": paper["evidence_level"], "source_verified": True,
                     "corpus_id": DEMO_CORPUS_ID, "abstract": paper.get("abstract") or None})
        # Same matching rule as science_roles.corpus_analysis; verify against the
        # saved display graph so a changed future taxonomy cannot silently drift.
        haystack = (paper["title"] + " " + paper.get("content", "")).casefold()
        tags = []
        for name, terms in method_terms.items():
            matched = [term for term in terms if re.search(r"(?<![a-z])" + re.escape(term.casefold()) + r"(?![a-z])", haystack)]
            if matched:
                tags.append(name)
                methods.append({"paper_id": paper_id, "method_name": name,
                                "matched_keywords": json.dumps(matched, ensure_ascii=False), "tagging_rule": TAGGING_RULE})
        if sorted(tags) != sorted(saved_tags.get(paper_id, [])):
            raise ValueError("方法标签与正式展示图表不一致，已停止导入")
    counts = dict(Counter(row["method_name"] for row in methods))
    if counts != snapshot.get("corpus_statistics", {}).get("method_mentions", {}):
        raise ValueError("方法统计与正式展示语料不一致")
    return rows, methods, {"source": str(Path(source).resolve()), "source_sha256": hashlib.sha256(raw).hexdigest(),
                           "corpus_id": DEMO_CORPUS_ID, "papers": len(rows), "method_rows": len(methods),
                           "method_counts": counts, "year_counts": dict(sorted(Counter(row["publication_year"] for row in rows).items()))}


DDL = [
    """CREATE TABLE IF NOT EXISTS public.research_papers (
        paper_id VARCHAR(64) PRIMARY KEY, title TEXT NOT NULL, publication_year INTEGER NOT NULL,
        authors TEXT, venue TEXT, doi TEXT, source_url TEXT NOT NULL, metadata_source TEXT,
        evidence_level VARCHAR(30) NOT NULL, source_verified BOOLEAN NOT NULL,
        corpus_id VARCHAR(120) NOT NULL, abstract TEXT, imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS public.research_paper_methods (
        paper_id VARCHAR(64) NOT NULL REFERENCES public.research_papers(paper_id),
        method_name VARCHAR(100) NOT NULL, matched_keywords TEXT NOT NULL, tagging_rule TEXT NOT NULL,
        PRIMARY KEY (paper_id, method_name)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_research_papers_year ON public.research_papers(publication_year)",
    "CREATE INDEX IF NOT EXISTS idx_research_methods_name ON public.research_paper_methods(method_name)",
]


def apply_rows(engine, papers, methods, *, expected_database="yayi_0929"):
    from sqlalchemy import text, bindparam, inspect
    if engine.dialect.name != "postgresql" or engine.url.database != expected_database:
        raise ValueError("连接数据库与本项目预期不符，未写入任何数据")
    columns = list(papers[0])
    with engine.begin() as connection:
        for statement in DDL:
            connection.execute(text(statement))
        inspector = inspect(connection)
        for table, required in (("research_papers", set(columns) | {"imported_at"}),
                                ("research_paper_methods", {"paper_id", "method_name", "matched_keywords", "tagging_rule"})):
            actual = {column["name"] for column in inspector.get_columns(table, schema="public")}
            if not required.issubset(actual):
                raise ValueError("同名表结构不兼容，事务已停止，不覆盖现有表")
        collisions = connection.execute(text(
            "SELECT paper_id FROM public.research_papers WHERE paper_id IN :ids AND corpus_id IS DISTINCT FROM :corpus"
        ).bindparams(bindparam("ids", expanding=True)), {"ids": [row["paper_id"] for row in papers], "corpus": DEMO_CORPUS_ID}).fetchall()
        if collisions:
            raise ValueError("文献标识已被其他语料使用，未覆盖现有数据")
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column not in {"paper_id", "corpus_id"})
        connection.execute(text(
            "INSERT INTO public.research_papers (" + ", ".join(columns) + ") VALUES (" + ", ".join(":" + column for column in columns) + ") "
            "ON CONFLICT (paper_id) DO UPDATE SET " + assignments + " WHERE research_papers.corpus_id = EXCLUDED.corpus_id"
        ), papers)
        connection.execute(text("""INSERT INTO public.research_paper_methods
            (paper_id, method_name, matched_keywords, tagging_rule)
            VALUES (:paper_id, :method_name, :matched_keywords, :tagging_rule)
            ON CONFLICT (paper_id, method_name) DO UPDATE SET matched_keywords = EXCLUDED.matched_keywords
            WHERE research_paper_methods.tagging_rule = EXCLUDED.tagging_rule"""), methods)
        return {"published_papers": connection.execute(text("SELECT count(*) FROM public.research_papers WHERE corpus_id=:corpus"),
                                                       {"corpus": DEMO_CORPUS_ID}).scalar_one()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT / "audit" / "demo-result.json")
    parser.add_argument("--apply", action="store_true", help="明确执行数据库写入；省略时仅离线校验")
    parser.add_argument("--expected-database", default="yayi_0929")
    args = parser.parse_args()
    papers, methods, summary = prepare_rows(args.source)
    if args.apply:
        from dotenv import load_dotenv
        load_dotenv(PROJECT / "backend" / ".env")
        from core.database import engine
        summary.update(apply_rows(engine, papers, methods, expected_database=args.expected_database))
    summary["mode"] = "applied" if args.apply else "dry_run_no_database_access"
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never dump connection strings, provider credentials or driver traces.
        print(json.dumps({"success": False, "error_type": type(exc).__name__, "message": "配置未完成；请核对语料与目标数据库，未输出连接凭据。"}, ensure_ascii=False))
        raise SystemExit(1)
