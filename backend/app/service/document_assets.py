"""Document identity, parser locators and authenticated asset metadata.

No source position is inferred from a filename, LLM answer or chunk index.
"""
import base64
import hashlib
import io
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

logger = logging.getLogger(__name__)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else str(value).encode("utf-8")).hexdigest()


def stable_chunk_id(document_id, version, index):
    return digest(f"{UUID(str(document_id))}:{version}:{int(index)}")


def asset_root():
    default = Path(__file__).resolve().parents[2] / "storage" / "knowledge" / "assets"
    return Path(os.getenv("DOCUMENT_ASSET_STORAGE_DIR", str(default))).resolve()


def safe_asset_path(path):
    if not path:
        return None
    candidate = Path(path).resolve()
    root = asset_root()
    return candidate if candidate.is_file() and candidate.is_relative_to(root) else None


def remove_asset_files(paths):
    for path in paths:
        candidate = safe_asset_path(path)
        if candidate:
            candidate.unlink(missing_ok=True)


def parser_value(value, *names):
    if hasattr(value, "to_map"):
        value = value.to_map()
    for name in names:
        found = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if found is not None and found != "":
            return found
    return None


def normalize_locator(value, inherited=None):
    """Preserve provider page conventions explicitly (page_id is not page)."""
    locator = {key: item for key, item in (inherited or {}).items() if key != "table_rows"}
    aliases = {
        "page": ("page", "Page", "page_number", "pageNumber", "PageNumber", "pageNum", "PageNum"),
        "page_id": ("page_id", "pageId", "PageId"),
        "bbox": ("bbox", "Bbox", "boundingBox", "BoundingBox", "bounding_box", "position", "Position", "pos", "Pos"),
        "page_width": ("page_width", "pageWidth", "PageWidth"),
        "page_height": ("page_height", "pageHeight", "PageHeight"),
        "coordinate_unit": ("coordinate_unit", "coordinateUnit", "CoordinateUnit"),
        "table_rows": ("rows", "Rows", "table_rows", "tableRows", "TableRows"),
        "row_index": ("row_index", "rowIndex", "RowIndex", "row", "Row"),
        "column_index": ("column_index", "columnIndex", "ColumnIndex", "col", "Col"),
        "row_start": ("ysc", "rowStart", "row_start"),
        "row_end": ("yec", "rowEnd", "row_end"),
        "column_start": ("xsc", "columnStart", "column_start"),
        "column_end": ("xec", "columnEnd", "column_end"),
        "equation_number": ("equation_number", "equationNumber", "EquationNumber", "formula_number", "formulaNumber"),
        "figure_number": ("figure_number", "figureNumber", "FigureNumber"),
        "table_number": ("table_number", "tableNumber", "TableNumber"),
        "block_id": ("block_id", "blockId", "BlockId", "layoutId", "layout_id", "uniqueId", "unique_id", "Id", "id"),
    }
    for key, names in aliases.items():
        item = parser_value(value, *names)
        if item is not None:
            try:
                locator[key] = json.loads(json.dumps(item, ensure_ascii=False))
            except (TypeError, ValueError):
                continue
    # DocMind's pageNum is zero-based (including 0 in its documented first-
    # page response). Keep the provider index alongside the human page number.
    page_index = parser_value(value, "pageNum", "PageNum")
    if isinstance(page_index, int) and not isinstance(page_index, bool) and page_index >= 0:
        locator.update(page=page_index + 1, page_index=page_index, page_index_base=0)
    elif isinstance(page_index, list) and all(isinstance(page, int) and page >= 0 for page in page_index):
        locator.update(page=[page + 1 for page in page_index], page_index=page_index, page_index_base=0)
    return locator


def normalize_layouts(layouts, text_reader):
    """Flatten text with exact offsets and collect nested structural objects."""
    texts, blocks, assets = [], [], []
    cursor = 0

    def safe_text(node):
        text = text_reader(node)
        # Parser image links contain expiring OSS credentials. Only persist
        # text labels and serve image bytes through our authenticated API.
        return re.sub(r"!\[([^\]]*)\]\(https?://[^)]+\)", r"[图像：\1]", text)

    def visit(node, parent_locator, parent_start, parent_end, root_text, root_start, path):
        locator = normalize_locator(node, parent_locator)
        raw_content = text_reader(node)
        content = safe_text(node)
        offset = root_text.find(content) if content else -1
        if offset >= 0 and root_text.find(content, offset + 1) >= 0:
            offset = -1  # repeated cell values cannot establish an exact span
        # If a nested plain-text representation does not occur in its parent's
        # markdown, associate it with the containing block, not a made-up span.
        start = root_start + offset if offset >= 0 else parent_start
        end = start + len(content) if offset >= 0 else parent_end
        kind = str(parser_value(node, "type", "Type", "layoutType", "layout_type", "blockType", "block_type") or "text").lower()
        if kind == "table":
            kind = "table"
            cells = parser_value(node, "cells", "Cells")
            if "table_rows" not in locator and isinstance(cells, list):
                locator["table_rows"] = [{"text": text_reader(cell), **normalize_locator(cell)} for cell in cells]
            if "table_rows" not in locator:
                lines = [line for line in content.splitlines() if line.strip().startswith("|") and not re.fullmatch(r"[\s|:\-]+", line)]
                if lines:
                    locator["table_rows"] = [{"row_index": index, "cells": [cell.strip() for cell in line.strip().strip("|").split("|")], "text": line} for index, line in enumerate(lines)]
                    locator["row_index_origin"] = "parser_markdown_order"
        elif "formula" in kind or "equation" in kind:
            kind = "equation"
        elif kind in {"image", "figure", "picture", "chart", "head_image", "foot_image"}:
            kind = "image"
        if kind == "equation" and "equation_number" not in locator:
            number = re.search(r"(?:\\tag\{([^}]+)\}|(?:\s|,)\((\d+[A-Za-z]?)\))\s*(?:\$\$)?\s*$", content)
            if number:
                locator.update(equation_number=number.group(1) or number.group(2), equation_number_source="parser_text")
        image_url = parser_value(node, "image_url", "imageUrl", "ImageUrl")
        image_data = parser_value(node, "image_base64", "imageBase64", "ImageBase64")
        if kind == "image" and not image_url:
            match = re.search(r"!\[[^\]]*\]\((https?://[^)]+)\)", raw_content)
            if match:
                image_url = match.group(1)
        if image_url or image_data:
            kind = "image"
        record = {"start": start, "end": end, "locator": locator, "block_key": path, "type": kind}
        blocks.append(record)
        if kind in {"table", "equation", "image"}:
            asset = {**record, "type": kind, "content": content, "image_url": image_url, "image_base64": image_data}
            assets.append(asset)
        for key in ("blocks", "Blocks", "cells", "Cells", "layouts", "Layouts"):
            nested = parser_value(node, key)
            if isinstance(nested, list):
                for index, child in enumerate(nested):
                    visit(child, locator, start, end, root_text, root_start, f"{path}/{key}/{index}")

    for index, layout in enumerate(layouts):
        content = safe_text(layout)
        start = cursor
        if content:
            texts.append(content)
            cursor += len(content) + 1
        visit(layout, {}, start, max(start, cursor - 1), content, start, str(index))
    return {"text": "\n".join(texts) + ("\n" if texts else ""), "blocks": blocks, "assets": assets}


def chunk_text_with_offsets(text, chunk_size=500, overlap=50, blocks=None):
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size")
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        sample = text[start:end]
        if end < len(text):
            for sep in ["。", "！", "？", ".", "!", "?", "\n"]:
                offset = sample.rfind(sep)
                if offset > chunk_size // 2:
                    end = start + offset + 1
                    break
        # Keep a small structural block whole. Very long blocks still split
        # with their shared block key and locator on every overlapping chunk.
        for block in blocks or []:
            if block.get("type") in {"table", "equation"} and block["start"] < end < block["end"]:
                if block["end"] - start <= chunk_size * 2:
                    end = block["end"]
        raw = text[start:end]
        if raw.strip():
            actual_start = start + len(raw) - len(raw.lstrip())
            actual_end = end - len(raw) + len(raw.rstrip())
            chunks.append({"content": text[actual_start:actual_end], "start": actual_start, "end": actual_end})
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _image_bytes(asset, original_path):
    encoded = asset.get("image_base64")
    url = asset.get("image_url")
    raw = None
    if encoded:
        encoded = str(encoded).split(",", 1)[-1]
        if len(encoded) <= 28 * 1024 * 1024:
            raw = base64.b64decode(encoded, validate=True)
    elif url:
        # Only fetch parser-hosted objects, never arbitrary addresses extracted
        # from document text; do not follow redirects or log signed URLs.
        parsed = urlparse(str(url))
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.hostname.endswith(".aliyuncs.com") and parsed.port in (None, 443):
            import requests
            secure_url = parsed._replace(scheme="https").geturl()
            with requests.get(secure_url, timeout=(10, 30), stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("Unexpected image response")
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 20 * 1024 * 1024:
                        raise ValueError("Image too large")
                raw = bytes(data)
    if raw:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            target = io.BytesIO()
            image.save(target, format="PNG")
            return target.getvalue()
    # Crop only explicit one-based page numbers and known PDF point units.
    locator = asset.get("locator", {})
    page, bbox = locator.get("page"), locator.get("bbox")
    if str(original_path).lower().endswith(".pdf") and isinstance(page, int) and page > 0 and isinstance(bbox, list) and len(bbox) == 4 and locator.get("coordinate_unit") in {"pt", "pdf_points", "point"}:
        import fitz
        with fitz.open(original_path) as pdf:
            if page <= len(pdf):
                rectangle = fitz.Rect(bbox)
                if rectangle.is_empty or not pdf[page - 1].rect.contains(rectangle):
                    raise ValueError("Invalid PDF crop coordinates")
                return pdf[page - 1].get_pixmap(clip=rectangle, matrix=fitz.Matrix(2, 2)).tobytes("png")
    return None


def build_provenance(document_id, version, parsed, chunks, original_path, asset_sink=None):
    """Materialize assets once; overlapping chunks share the same asset IDs."""
    assets, warning = asset_sink if asset_sink is not None else [], []
    for raw in parsed.get("assets", []):
        asset_id = digest(f"{document_id}:{version}:{raw['type']}:{raw['block_key']}")
        content = raw.get("content", "")
        media_type, payload = "application/json", None
        if raw["type"] == "image":
            try:
                payload = _image_bytes(raw, original_path)
            except Exception as exc:
                logger.warning("Document image extraction failed (%s)", type(exc).__name__)
            if payload:
                media_type = "image/png"
            else:
                warning.append("部分图片未提供可保存图像或明确裁切坐标，已保留原文定位")
        if payload is None:
            payload = json.dumps({"type": raw["type"], "content": content, "locator": raw["locator"]}, ensure_ascii=False).encode("utf-8")
        root = asset_root()
        root.mkdir(parents=True, exist_ok=True)
        path = root / (asset_id + (".png" if media_type == "image/png" else ".json"))
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, prefix=".asset-", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
            temporary_path.replace(path)
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
        assets.append({"asset_id": asset_id, "document_id": str(document_id), "document_version": version,
                       "type": raw["type"], "content": content, "file_path": str(path), "media_type": media_type,
                       "locator": raw["locator"], "content_hash": digest(payload), "start": raw["start"], "end": raw["end"]})
    records = []
    for index, chunk in enumerate(chunks):
        def overlaps(item):
            return item["start"] < chunk["end"] and item["end"] > chunk["start"]
        locators = []
        for block in parsed.get("blocks", []):
            if overlaps(block) and block.get("locator") and block["locator"] not in locators:
                compact_locator = {key: item for key, item in block["locator"].items() if key != "table_rows"}
                if compact_locator not in locators:
                    locators.append(compact_locator)
        records.append({"chunk_id": stable_chunk_id(document_id, version, index), "chunk_index": index,
                        "text_start": chunk["start"], "text_end": chunk["end"], "content_hash": digest(chunk["content"]),
                        "locators": locators, "asset_ids": [asset["asset_id"] for asset in assets if overlaps(asset)]})
    return assets, records, list(dict.fromkeys(warning))


def persist_provenance(db, document, collection_name, result):
    from models.knowledge import DocumentAsset, DocumentChunkProvenance
    from service.milvus_service import normalize_collection_name
    version = result["document_version"]
    # Reprocessing the same file is idempotent without deleting other versions.
    db.query(DocumentChunkProvenance).filter_by(document_id=document.id, document_version=version).delete(synchronize_session=False)
    db.query(DocumentAsset).filter_by(document_id=document.id, document_version=version).delete(synchronize_session=False)
    for asset in result.get("assets", []):
        db.add(DocumentAsset(id=asset["asset_id"], document_id=document.id, document_version=version,
                             asset_type=asset["type"], content=asset["content"], file_path=asset["file_path"],
                             media_type=asset["media_type"], locator=asset["locator"], content_hash=asset["content_hash"]))
    for record in result.get("provenance", []):
        db.add(DocumentChunkProvenance(document_id=document.id, document_version=version,
                                      collection_name=normalize_collection_name(collection_name), **record))
    db.flush()


def asset_response(asset, knowledge_base_id, summary=False):
    locator = asset.locator or {}
    if summary:
        locator = {key: value for key, value in locator.items() if key != "table_rows"}
    return {"asset_id": asset.id, "document_id": str(asset.document_id), "document_version": asset.document_version,
            "type": asset.asset_type, "content": (asset.content or "")[:400] if summary else asset.content, "locator": locator,
            "media_type": asset.media_type, "content_hash": asset.content_hash,
            "download_url": f"/knowledge-bases/{knowledge_base_id}/documents/{asset.document_id}/assets/{asset.id}/download" if safe_asset_path(asset.file_path) else None}


def enrich_chunks(db, collection_name, chunks, knowledge_base_id=None):
    """Two batch queries, with ownership scope supplied by authenticated caller."""
    from models.knowledge import Document, DocumentAsset, DocumentChunkProvenance
    from sqlalchemy.orm import joinedload
    from service.milvus_service import normalize_collection_name
    ids = [chunk.get("id") or chunk.get("chunk_id") for chunk in chunks]
    if not ids:
        return chunks
    query = db.query(DocumentChunkProvenance).options(joinedload(DocumentChunkProvenance.document)).join(Document).filter(
        DocumentChunkProvenance.collection_name == normalize_collection_name(collection_name),
        DocumentChunkProvenance.chunk_id.in_(ids), Document.status == "completed")
    if knowledge_base_id is not None:
        query = query.filter(Document.knowledge_base_id == knowledge_base_id)
    records = query.all()
    by_id = {row.chunk_id: row for row in records}
    asset_ids = {key for row in records for key in (row.asset_ids or [])}
    asset_query = db.query(DocumentAsset).join(Document).filter(DocumentAsset.id.in_(asset_ids))
    if knowledge_base_id is not None:
        asset_query = asset_query.filter(Document.knowledge_base_id == knowledge_base_id)
    by_asset = {asset.id: asset for asset in asset_query.all()} if asset_ids else {}
    output = []
    for chunk in chunks:
        row = dict(chunk)
        chunk_id = row.get("id") or row.get("chunk_id")
        row.update(chunk_id=chunk_id, locators=[], assets=[])
        record = by_id.get(chunk_id)
        if record:
            kb_id = knowledge_base_id or record.document.knowledge_base_id
            row.update(document_id=str(record.document_id), document_version=record.document_version,
                       locators=[{key: value for key, value in locator.items() if key != "table_rows"} for locator in record.locators or []], content_hash=record.content_hash,
                       evidence_id="ev_" + record.chunk_id, text_start=record.text_start, text_end=record.text_end,
                       download_url=f"/knowledge-bases/{kb_id}/documents/{record.document_id}/download")
            row["assets"] = [asset_response(by_asset[key], kb_id, summary=True) for key in record.asset_ids or [] if key in by_asset and by_asset[key].document_id == record.document_id]
        output.append(row)
    return output
