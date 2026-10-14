"""Bounded probes: isolated Milvus synthetic vectors, optional one-page DocMind upload.

All vectors are artificial unit vectors, never real model embeddings. No user
collections or PostgreSQL rows are modified; every temporary collection is cleaned.
"""
import argparse
import io
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env")

results = []


def record(test, passed, **details):
    result = {"test": test, "passed": bool(passed), **details}
    results.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def vector_probe():
    from pymilvus import utility
    from service.milvus_service import MilvusService, normalize_collection_name
    from service.memory_service import MemoryService

    run_id = uuid.uuid4().hex
    original = "kb_审计临时_" + run_id
    renamed = "kb_审计改名_" + run_id
    memory_name = "audit_memory_" + run_id
    names = [normalize_collection_name(original), normalize_collection_name(renamed), memory_name]
    vector = [1.0] + [0.0] * 1023
    service = MilvusService()
    # Refuse to touch any collection that pre-dates this invocation.
    assert all(not utility.has_collection(name) for name in names)
    try:
        count = service.insert_documents(original, [{
            "id": run_id, "doc_id": run_id, "kb_id": original, "filename": 'audit"中文.txt',
            "content": "Synthetic integration fixture; this is not a model embedding.",
            "chunk_index": 0, "vector": vector,
        }])
        record("synthetic 1024d Chinese KB vector insert", count == 1, embedding_source="fixed synthetic unit vector")
        hits = service.search(original, vector, top_k=1)
        record("Milvus COSINE vector search", len(hits) == 1 and hits[0]["doc_id"] == run_id,
               hit_count=len(hits), score=float(hits[0]["score"]) if hits else None)
        chunks = service.get_chunks_by_filename(original, 'audit"中文.txt')
        record("quoted filename chunk retrieval", len(chunks) == 1)
        service.rename_collection(original, renamed)
        chunks = service.get_chunks_by_filename(renamed, 'audit"中文.txt')
        record("Chinese KB rename retains chunks", len(chunks) == 1 and not utility.has_collection(names[0]))
        service.delete_by_doc_id(renamed, run_id)
        for _ in range(10):
            chunks = service.get_chunks_by_filename(renamed, 'audit"中文.txt')
            if not chunks:
                break
            time.sleep(0.5)
        record("document deletion removes vectors", not chunks)
        service.delete_collection(renamed)
        record("knowledge base deletion removes collection", not utility.has_collection(names[1]))

        # MemoryService's real schema / insert / search, with only the embedding
        # function replaced. Patch the collection constant so existing memories
        # are never accessed or changed.
        memory = MemoryService.__new__(MemoryService)
        memory._milvus = None
        owner = str(uuid.uuid4())
        other = str(uuid.uuid4())
        with patch("service.memory_service.MEMORY_COLLECTION_NAME", memory_name), \
                patch("service.memory_service.generate_embedding", return_value=vector):
            own_ids = memory._store_memory_vectors(str(uuid.uuid4()), owner, str(uuid.uuid4()), {"summary": "audit owner summary"})
            other_ids = memory._store_memory_vectors(str(uuid.uuid4()), other, str(uuid.uuid4()), {"summary": "audit other summary"})
            record("memory real Milvus insert with synthetic vectors", len(own_ids) == len(other_ids) == 1,
                   embedding_source="fixed synthetic unit vector")
            hits = memory._retrieve_vector_memories(owner, "synthetic query", top_k=10)
            record("memory search enforces user filter", len(hits) == 1 and hits[0]["id"] == own_ids[0],
                   hit_count=len(hits))
    finally:
        for name in names:
            if utility.has_collection(name):
                utility.drop_collection(name)
        record("temporary Milvus collection cleanup", all(not utility.has_collection(name) for name in names))


def redact(message):
    result = str(message or "")
    for name in ("DOCMIND_ACCESS_KEY_ID", "DOCMIND_ACCESS_KEY_SECRET", "DASHSCOPE_API_KEY"):
        value = os.getenv(name)
        if value:
            result = result.replace(value, "[REDACTED]")
    return result[:500]


def docmind_probe():
    from PyPDF2 import PdfWriter
    from PyPDF2.generic import DecodedStreamObject, DictionaryObject, NameObject
    from service.docmind_service import DocMindService
    from alibabacloud_docmind_api20220711 import models
    from alibabacloud_tea_util import models as util_models

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    page = writer.pages[0]
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 100 Td (Synthetic audit document, no user data.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    buf = io.BytesIO()
    writer.write(buf)
    client = DocMindService().client
    # Exactly one bounded submit; SDK-managed upload uses only this tiny fixture.
    try:
        response = client.submit_doc_parser_job_advance(models.SubmitDocParserJobAdvanceRequest(
            file_url_object=io.BytesIO(buf.getvalue()), file_name="synthetic-audit.pdf", file_name_extension="pdf"),
            util_models.RuntimeOptions(read_timeout=20000, connect_timeout=10000, autoretry=False))
        body = response.body
        data = getattr(body, "data", None)
        record("DocMind bounded synthetic PDF submit", bool(data and getattr(data, "id", None)),
               http_status=getattr(response, "status_code", None), body_type=type(body).__name__,
               data_type=type(data).__name__, code=redact(getattr(body, "code", None)),
               message=redact(getattr(body, "message", None)), has_task_id=bool(data and getattr(data, "id", None)))
    except Exception as exc:
        # Avoid serializing SDK objects/headers or signed upload URLs.
        record("DocMind bounded synthetic PDF submit", False, exception_type=type(exc).__name__,
               code=redact(getattr(exc, "code", None)), message=redact(getattr(exc, "message", "request failed")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docmind", action="store_true")
    args = parser.parse_args()
    try:
        vector_probe()
        if args.docmind:
            docmind_probe()
    finally:
        (ROOT / "audit" / "live_vector_docmind_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
