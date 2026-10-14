from pathlib import Path
p=Path(r'D:/ldj/01/source/industry_information_assistant/backend/app/service/embedding_service.py')
s=p.read_text(encoding='utf-8')
start=s.index('    try:\n        client = OpenAI', s.index('def generate_embedding'))
end=s.index('\n\ndef rerank_similarity',start)
new='''    from service.response_cache import RedisJSONCache
    import hashlib
    import math
    cache = RedisJSONCache("embedding-v1", int(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "86400")))
    single = isinstance(text, str)
    texts = [text] if single else text
    if not isinstance(texts, list):
        return None
    if not texts:
        return []
    credential_scope = hashlib.sha256(api_key.encode()).hexdigest()
    keys = [[base_url, model_name, dimensions, encoding_format, credential_scope, value] for value in texts]
    def valid(vector):
        return (isinstance(vector, list) and len(vector) == dimensions
                and all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector))
    vectors = [cache.get(key) if encoding_format == "float" else None for key in keys]
    missing = {}
    for index, vector in enumerate(vectors):
        if not valid(vector):
            vectors[index] = None
            missing.setdefault(texts[index], []).append(index)
    try:
        if missing:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=60, max_retries=1)
            pending = list(missing)
            batch_size = max(1, min(int(max_batch_size), 10))
            for offset in range(0, len(pending), batch_size):
                batch = pending[offset:offset + batch_size]
                try:
                    completion = client.embeddings.create(model=model_name, input=batch,
                                                          dimensions=dimensions, encoding_format=encoding_format)
                    for fallback_index, item in enumerate(completion.data):
                        item_index = getattr(item, "index", fallback_index)
                        if not isinstance(item_index, int) or not 0 <= item_index < len(batch):
                            continue
                        vector = item.embedding
                        if encoding_format == "float" and not valid(vector):
                            continue
                        for index in missing[batch[item_index]]:
                            vectors[index] = vector
                        if encoding_format == "float":
                            cache.set(keys[missing[batch[item_index]][0]], vector)
                except Exception as exc:
                    print(f"Embedding request failed ({type(exc).__name__})")
    except Exception as exc:
        print(f"Embedding client failed ({type(exc).__name__})")
    return vectors[0] if single else vectors
'''
p.write_text(s[:start]+new+s[end:],encoding='utf-8')
