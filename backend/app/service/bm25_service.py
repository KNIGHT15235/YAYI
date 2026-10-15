"""Rebuildable, bounded BM25 indexes over existing Milvus chunk text.

No second persistent store: Milvus remains authoritative. Cached indexes only
contain IDs and term statistics; callers fetch current rows before returning hits.
"""
from array import array
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
import heapq
import math
import os
import re
import threading
import time
import unicodedata


def _number(name, default, minimum, maximum, cast=float):
    try:
        value = cast(os.getenv(name, str(default)))
        if not math.isfinite(value):
            return default
        return max(minimum, min(value, maximum))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class HybridConfig:
    enabled: bool = True
    candidates: int = 50
    rerank_candidates: int = 50
    rrf_k: int = 60
    k1: float = 1.2
    b: float = 0.75
    cache_ttl: float = 60
    cache_entries: int = 2
    max_chunks: int = 50000
    max_postings: int = 2000000
    build_timeout: float = 30

    @classmethod
    def from_env(cls):
        return cls(
            enabled=os.getenv("RETRIEVAL_HYBRID_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"},
            candidates=_number("RETRIEVAL_CANDIDATES", 50, 1, 200, int),
            rerank_candidates=_number("RETRIEVAL_RERANK_CANDIDATES", 50, 1, 200, int),
            rrf_k=_number("RETRIEVAL_RRF_K", 60, 1, 1000, int),
            k1=_number("BM25_K1", 1.2, 0.1, 3),
            b=_number("BM25_B", 0.75, 0, 1),
            cache_ttl=_number("BM25_CACHE_TTL_SECONDS", 60, 0, 3600),
            cache_entries=_number("BM25_CACHE_ENTRIES", 2, 1, 8, int),
            max_chunks=_number("BM25_MAX_CHUNKS", 50000, 1, 200000, int),
            max_postings=_number("BM25_MAX_POSTINGS", 2000000, 1, 10000000, int),
            build_timeout=_number("BM25_BUILD_TIMEOUT_SECONDS", 30, 1, 120),
        )


# Full identifiers (IL-6, GPT-4, 10.1000/xyz) and their components both match.
# Chinese spans use the same search tokenizer at indexing and query time.
_PARTS = re.compile(r"[\u3400-\u9fff]+|[^\W_]+(?:[._/+\-][^\W_]+)*", re.UNICODE)
_CJK = re.compile(r"[\u3400-\u9fff]+")


def tokenize(text):
    import jieba
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    text = _CJK.sub(lambda match: " " + match.group() + " ", text)
    terms = []
    for match in _PARTS.finditer(text):
        part = match.group()
        if _CJK.search(part):
            terms.extend(term for term in jieba.cut_for_search(part, HMM=False) if term.strip())
        else:
            terms.append(part)
            if re.search(r"[._/+\-]", part):
                terms.extend(re.findall(r"[^\W_]+", part))
    return terms


class BM25Unavailable(RuntimeError):
    """A complete, fresh-enough keyword index could not be built within budget."""


class BM25Index:
    def __init__(self, rows, config, deadline):
        self.ids = []
        self.lengths = array("I")
        self.postings = {}
        seen = set()
        posting_count = 0
        # Iterators must be closed even on limits / malformed rows / tokenizer failure.
        try:
            for row in rows:
                if time.monotonic() > deadline:
                    raise BM25Unavailable("keyword index build timed out")
                identity = row["id"]
                if identity in seen:
                    continue
                if len(self.ids) >= config.max_chunks:
                    raise BM25Unavailable("keyword corpus exceeds BM25_MAX_CHUNKS")
                frequencies = Counter(tokenize(row.get("content", "")))
                posting_count += len(frequencies)
                if posting_count > config.max_postings:
                    raise BM25Unavailable("keyword index exceeds BM25_MAX_POSTINGS")
                ordinal = len(self.ids)
                seen.add(identity)
                self.ids.append(identity)
                self.lengths.append(sum(frequencies.values()))
                for term, count in frequencies.items():
                    if term not in self.postings:
                        self.postings[term] = array("I")
                    self.postings[term].extend((ordinal, count))
            if time.monotonic() > deadline:
                raise BM25Unavailable("keyword index build timed out")
        finally:
            close = getattr(rows, "close", None)
            if close:
                close()
        self.average_length = sum(self.lengths) / len(self.ids) if self.ids else 0

    def search(self, query, top_k, k1=1.2, b=0.75):
        if not self.average_length:
            return []
        scores = defaultdict(float)
        for term in sorted(set(tokenize(query))):
            postings = self.postings.get(term, ())
            frequency = len(postings) // 2
            if not frequency:
                continue
            idf = math.log1p((len(self.ids) - frequency + 0.5) / (frequency + 0.5))
            for offset in range(0, len(postings), 2):
                ordinal, count = postings[offset], postings[offset + 1]
                norm = k1 * (1 - b + b * self.lengths[ordinal] / self.average_length)
                scores[ordinal] += idf * count * (k1 + 1) / (count + norm)
        best = heapq.nsmallest(top_k, scores, key=lambda i: (-scores[i], self.ids[i]))
        return [(self.ids[i], scores[i]) for i in best]


class BM25Cache:
    """Per-service LRU. One builder at a time bounds concurrent memory use.

    Invalidation never waits on a scan; a generation check prevents publishing
    an index built across a local write. Other processes refresh via the TTL.
    """
    def __init__(self):
        self._entries = OrderedDict()
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()
        self._generation = 0

    def invalidate(self, *collections):
        with self._lock:
            self._generation += 1
            for key in list(self._entries):
                if key[0] in collections:
                    del self._entries[key]

    def get(self, collection, kb_id, loader, config):
        key = (collection, kb_id, config.max_chunks, config.max_postings)

        def cached():
            with self._lock:
                now = time.monotonic()
                for stale in list(self._entries):
                    if now - self._entries[stale][0] >= config.cache_ttl:
                        del self._entries[stale]
                entry = self._entries.get(key)
                if entry:
                    self._entries.move_to_end(key)
                    return entry[1]
            return None

        index = cached()
        if index is not None:
            return index
        # Do not let concurrent research tasks queue behind a slow cold scan.
        if not self._build_lock.acquire(timeout=1):
            raise BM25Unavailable("keyword index builder busy")
        try:
            index = cached()
            if index is not None:
                return index
            with self._lock:
                generation = self._generation
                while len(self._entries) >= config.cache_entries:
                    self._entries.popitem(last=False)
            index = BM25Index(loader(), config, time.monotonic() + config.build_timeout)
            with self._lock:
                if generation != self._generation:
                    raise BM25Unavailable("corpus changed during keyword index build")
                self._entries[key] = (time.monotonic(), index)
            return index
        finally:
            self._build_lock.release()


def reciprocal_rank_fusion(dense, lexical, k=60):
    """Equal-weight RRF. Keep cosine scores separate from BM25 / fusion scores."""
    merged = {}
    for route, rows in (("vector", dense), ("bm25", lexical)):
        seen = set()
        rank = 0
        for row in rows:
            identity = row["id"]
            if identity in seen:
                continue
            seen.add(identity)
            rank += 1
            if identity not in merged:
                merged[identity] = {**row, "score": row.get("score"), "rrf_score": 0.0,
                                    "retrieval_sources": []}
            target = merged[identity]
            target["rrf_score"] += 1.0 / (k + rank)
            target["retrieval_sources"].append(route)
            if route == "bm25":
                target["bm25_score"] = row["bm25_score"]
    # Stable sort keeps the existing vector order on equal fused scores.
    return sorted(merged.values(), key=lambda row: -row["rrf_score"])
