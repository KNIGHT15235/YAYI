
"""知识库管理路由"""
import os
import hashlib
import tempfile
from pathlib import Path
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from core.database import get_db
from models.knowledge import KnowledgeBase, Document, DocumentAsset, DocumentChunkProvenance
from service.document_assets import (persist_provenance, enrich_chunks, asset_response,
                                     safe_asset_path, remove_asset_files)
from models.user import User
from router.auth_router import get_current_user_required
from service.knowledge_access import collection_for_name, ensure_collection_is_exclusive
from schemas.knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseWithDocuments,
    DocumentResponse,
    DocumentUploadResponse,
    KnowledgeSearchRequest,
    DocumentAssetListResponse,
)

router = APIRouter(prefix="/knowledge-bases", tags=["知识库管理"])

# Preserve originals outside the web root, served only through an authorized route.
UPLOAD_DIR = str(Path(os.getenv("KNOWLEDGE_STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage" / "knowledge"))).resolve())
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_UPLOAD_SIZE = 100 * 1024 * 1024

# 支持的文件类型
ALLOWED_EXTENSIONS = {
    # 文档类型
    '.pdf', '.docx', '.doc', '.txt', '.md', '.html', '.xlsx', '.xls', '.pptx', '.ppt',
    # 图片类型
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
    # 代码/数据类型
    '.py', '.js', '.ts', '.json', '.yaml', '.yml', '.xml', '.csv',
}


def get_file_extension(filename: str) -> str:
    """获取文件扩展名"""
    return os.path.splitext(filename)[1].lower()


def stored_original(path):
    """Only permit files inside directories managed by this uploader."""
    if not path:
        return None
    candidate = Path(path).resolve()
    roots = (Path(UPLOAD_DIR).resolve(), Path("/tmp/knowledge_uploads").resolve())
    if candidate.is_file() and any(candidate.is_relative_to(root) for root in roots):
        return candidate
    return None


def remove_original(path):
    original = stored_original(path)
    if original:
        original.unlink(missing_ok=True)


def ensure_documents_are_idle(db: Session, kb: KnowledgeBase):
    busy = db.query(Document).filter(
        Document.knowledge_base_id == kb.id,
        Document.status.in_(["pending", "processing"]),
    ).first()
    if busy:
        raise HTTPException(status_code=409, detail="知识库有正在处理的文档，请处理结束后重试")


def kb_to_response(kb: KnowledgeBase) -> KnowledgeBaseResponse:
    """将知识库模型转换为响应"""
    return KnowledgeBaseResponse(
        id=str(kb.id),
        name=kb.name,
        description=kb.description,
        document_count=kb.document_count or 0,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


def doc_to_response(doc: Document) -> DocumentResponse:
    """将文档模型转换为响应"""
    return DocumentResponse(
        id=str(doc.id),
        knowledge_base_id=str(doc.knowledge_base_id),
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        chunk_count=doc.chunk_count or 0,
        error_message=doc.error_message,
        download_available=stored_original(doc.file_path) is not None,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def process_document(document_id: str, file_path: str, kb_name: str, db_session_factory):
    """Parse and index the document while retaining its authorized original."""
    from service.docmind_service import process_document_with_docmind

    # 创建新的数据库会话
    db = db_session_factory()
    try:
        # 获取文档记录
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            remove_original(file_path)
            return

        # 更新状态为处理中
        doc.status = "processing"
        db.commit()

        try:
            # Legacy layout uses the knowledge base name as the Milvus collection.
            index_name = f"kb_{kb_name}".lower().replace(" ", "_")

            # 使用 DocMind 处理文档
            result = process_document_with_docmind(
                file_path=file_path,
                file_name=doc.filename,
                index_name=index_name,
                document_id=document_id,
            )

            if result["success"]:
                if result.get("provenance"):
                    persist_provenance(db, doc, index_name, result)
                doc.status = "completed"
                doc.chunk_count = result["document_count"]
                doc.error_message = None
            else:
                doc.status = "failed"
                doc.error_message = result["message"]
            db.commit()

        except Exception as e:
            db.rollback()
            # Compensate vector/file writes when relational persistence fails;
            # the document remains visible as failed, rather than untraceable.
            if "result" in locals() and result.get("success") and result.get("provenance"):
                from service.milvus_service import get_milvus_service
                try:
                    get_milvus_service().delete_by_doc_id(index_name, document_id)
                except Exception:
                    pass  # failed document remains excluded from search
                remove_asset_files([asset["file_path"] for asset in result.get("assets", [])])
            doc.status = "failed"
            doc.error_message = str(e)
            db.commit()

    finally:
        db.close()


@router.get("", response_model=List[KnowledgeBaseResponse])
async def get_knowledge_bases(
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """获取用户的知识库列表"""
    kbs = db.query(KnowledgeBase).filter(
        KnowledgeBase.user_id == current_user.id
    ).order_by(KnowledgeBase.updated_at.desc()).all()

    return [kb_to_response(kb) for kb in kbs]


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    kb_data: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """创建知识库"""
    # 检查是否已存在同名知识库
    existing = db.query(KnowledgeBase).filter(
        KnowledgeBase.user_id == current_user.id,
        KnowledgeBase.name == kb_data.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已存在同名知识库"
        )

    kb = KnowledgeBase(
        user_id=current_user.id,
        name=kb_data.name,
        description=kb_data.description,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)

    return kb_to_response(kb)


@router.get("/{kb_id}", response_model=KnowledgeBaseWithDocuments)
async def get_knowledge_base(
    kb_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """获取知识库详情（包含文档列表）"""
    try:
        kb_uuid = UUID(kb_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的知识库ID格式"
        )

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.user_id == current_user.id
    ).first()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )

    documents = db.query(Document).filter(
        Document.knowledge_base_id == kb.id
    ).order_by(Document.created_at.desc()).all()

    return KnowledgeBaseWithDocuments(
        id=str(kb.id),
        name=kb.name,
        description=kb.description,
        document_count=kb.document_count or 0,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
        documents=[doc_to_response(doc) for doc in documents],
    )


@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: str,
    kb_data: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """更新知识库"""
    try:
        kb_uuid = UUID(kb_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的知识库ID格式"
        )

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.user_id == current_user.id
    ).first()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )

    if kb_data.name is not None:
        # 检查是否与其他知识库重名
        existing = db.query(KnowledgeBase).filter(
            KnowledgeBase.user_id == current_user.id,
            KnowledgeBase.name == kb_data.name,
            KnowledgeBase.id != kb_uuid
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="已存在同名知识库"
            )
        if kb_data.name != kb.name:
            ensure_collection_is_exclusive(db, kb)
            ensure_collection_is_exclusive(db, kb, kb_data.name)
            ensure_documents_are_idle(db, kb)
            from service.milvus_service import get_milvus_service
            try:
                old_collection = collection_for_name(kb.name)
                new_collection = collection_for_name(kb_data.name)
                get_milvus_service().rename_collection(
                    old_collection, new_collection
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            except Exception:
                raise HTTPException(status_code=503, detail="知识库向量集合重命名失败，请稍后重试")
            from service.milvus_service import normalize_collection_name
            db.query(DocumentChunkProvenance).filter(
                DocumentChunkProvenance.document_id.in_(db.query(Document.id).filter(Document.knowledge_base_id == kb.id)),
            ).update({DocumentChunkProvenance.collection_name: normalize_collection_name(new_collection)}, synchronize_session=False)
            kb.name = kb_data.name

    if kb_data.description is not None:
        kb.description = kb_data.description

    db.commit()
    db.refresh(kb)

    return kb_to_response(kb)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    kb_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """删除知识库"""
    try:
        kb_uuid = UUID(kb_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的知识库ID格式"
        )

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.user_id == current_user.id
    ).first()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )

    ensure_collection_is_exclusive(db, kb)
    ensure_documents_are_idle(db, kb)
    from service.milvus_service import get_milvus_service
    try:
        deleted = get_milvus_service().delete_collection(collection_for_name(kb.name))
    except Exception:
        deleted = False
    if not deleted:
        raise HTTPException(status_code=503, detail="知识库向量删除失败，未删除知识库记录")
    original_paths = [doc.file_path for doc in kb.documents]
    asset_paths = [asset.file_path for doc in kb.documents for asset in doc.assets]
    db.delete(kb)
    db.commit()
    for original_path in original_paths:
        remove_original(original_path)
    remove_asset_files(asset_paths)
    return None


@router.post("/{kb_id}/documents", response_model=DocumentUploadResponse)
async def upload_document(
    kb_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """上传文档到知识库"""
    try:
        kb_uuid = UUID(kb_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的知识库ID格式"
        )

    # 验证知识库存在
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.user_id == current_user.id
    ).first()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )

    # 验证文件类型
    ensure_collection_is_exclusive(db, kb)
    filename = os.path.basename((file.filename or "").replace("\\", "/"))
    ext = get_file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {ext}，支持的类型: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Persist the original with a generated filename, never a client supplied path.
    file_path = None
    file_size = 0
    try:
        with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=ext, delete=False) as buffer:
            file_path = buffer.name
            while chunk := await file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="单文件最大支持 100MB")
                buffer.write(chunk)
    except HTTPException:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise
    except Exception as e:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件保存失败: {str(e)}"
        )

    # 创建文档记录
    doc = Document(
        knowledge_base_id=kb_uuid,
        user_id=current_user.id,
        filename=filename,
        file_type=ext[1:] if ext else None,  # 去掉点
        file_size=file_size,
        file_path=file_path,
        status="pending",
    )
    db.add(doc)

    # 更新知识库文档计数
    kb.document_count = (kb.document_count or 0) + 1

    db.commit()
    db.refresh(doc)

    # 获取数据库会话工厂
    from core.database import SessionLocal

    # 在后台处理文档
    background_tasks.add_task(
        process_document,
        str(doc.id),
        file_path,
        kb.name,
        SessionLocal
    )

    return DocumentUploadResponse(
        id=str(doc.id),
        filename=doc.filename,
        process_status="pending",
        message="文档已上传，正在后台处理中"
    )


@router.get("/{kb_id}/documents", response_model=List[DocumentResponse])
async def get_documents(
    kb_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """获取知识库的文档列表"""
    try:
        kb_uuid = UUID(kb_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的知识库ID格式"
        )

    # 验证知识库存在
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.user_id == current_user.id
    ).first()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )

    documents = db.query(Document).filter(
        Document.knowledge_base_id == kb_uuid
    ).order_by(Document.created_at.desc()).all()

    return [doc_to_response(doc) for doc in documents]


@router.get("/{kb_id}/documents/{doc_id}/chunks")
async def get_document_chunks(
    kb_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """获取文档的所有切片"""
    from service.milvus_service import get_milvus_service

    try:
        kb_uuid = UUID(kb_id)
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的ID格式"
        )

    # 验证知识库存在
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.user_id == current_user.id
    ).first()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )

    # 获取文档
    doc = db.query(Document).filter(
        Document.id == doc_uuid,
        Document.knowledge_base_id == kb_uuid
    ).first()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文档不存在"
        )

    if doc.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文档尚未处理完成"
        )

    # 从 Milvus 获取切片
    ensure_collection_is_exclusive(db, kb)
    collection_name = f"kb_{kb.name}".lower().replace(" ", "_")
    print(f"[get_document_chunks] 查询切片: collection={collection_name}, filename={doc.filename}")

    try:
        milvus = get_milvus_service()
        has_provenance = db.query(DocumentChunkProvenance).filter_by(document_id=doc.id).first() is not None
        vector_doc_id = str(doc.id) if has_provenance else hashlib.md5(doc.filename.encode()).hexdigest()
        chunks = milvus.get_chunks_by_doc_id(collection_name, vector_doc_id)
        chunks = enrich_chunks(db, collection_name, chunks, kb.id)
        print(f"[get_document_chunks] 找到 {len(chunks)} 个切片")
    except Exception as e:
        print(f"[get_document_chunks] Milvus 查询失败: {e}")
        # 返回空结果而不是报错
        chunks = []

    return {
        "document_id": str(doc.id),
        "filename": doc.filename,
        "chunk_count": len(chunks),
        "chunks": [
            {
                "index": chunk.get("chunk_index", i),
                "content": chunk.get("content", ""),
                "chunk_id": chunk.get("id"),
                "document_id": str(doc.id),
                "document_version": chunk.get("document_version"),
                "locators": chunk.get("locators", []),
                "assets": chunk.get("assets", []),
                "evidence_id": chunk.get("evidence_id"),
                "content_hash": chunk.get("content_hash"),
            }
            for i, chunk in enumerate(chunks)
        ]
    }


@router.delete("/{kb_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    kb_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """删除文档"""
    try:
        kb_uuid = UUID(kb_id)
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的ID格式"
        )

    # 验证知识库存在
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid,
        KnowledgeBase.user_id == current_user.id
    ).first()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在"
        )

    # 获取文档
    doc = db.query(Document).filter(
        Document.id == doc_uuid,
        Document.knowledge_base_id == kb_uuid
    ).first()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文档不存在"
        )

    ensure_collection_is_exclusive(db, kb)
    if doc.status in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="文档正在处理中，请处理结束后重试")
    # Legacy vectors use the filename hash as doc_id. Keep them until the last
    # record using that name is removed, so historical duplicates stay readable.
    duplicate_count = db.query(Document).filter(
        Document.knowledge_base_id == kb_uuid, Document.filename == doc.filename,
        ~Document.provenance.any(),
    ).count()
    has_provenance = db.query(DocumentChunkProvenance).filter_by(document_id=doc.id).first() is not None
    if has_provenance or duplicate_count <= 1:
        from service.milvus_service import get_milvus_service
        vector_doc_id = str(doc.id) if has_provenance else hashlib.md5(doc.filename.encode()).hexdigest()
        try:
            deleted = get_milvus_service().delete_by_doc_id(collection_for_name(kb.name), vector_doc_id)
        except Exception:
            deleted = False
        if not deleted:
            raise HTTPException(status_code=503, detail="文档向量删除失败，未删除文档记录")

    original_path = doc.file_path
    asset_paths = [asset.file_path for asset in doc.assets]

    # 更新知识库文档计数
    kb.document_count = max((kb.document_count or 0) - 1, 0)

    db.delete(doc)
    db.commit()
    remove_original(original_path)
    remove_asset_files(asset_paths)
    return None


def owned_kb(db, current_user, kb_id):
    try:
        kb_uuid = UUID(kb_id)
    except ValueError:
        raise HTTPException(400, "无效的知识库ID格式")
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == current_user.id,
    ).first()
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    return kb


@router.get("/{kb_id}/documents/{doc_id}/download")
def download_document(kb_id: str, doc_id: str,
                      current_user: User = Depends(get_current_user_required),
                      db: Session = Depends(get_db)):
    kb = owned_kb(db, current_user, kb_id)
    try:
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "无效的文档ID格式")
    doc = db.query(Document).filter(Document.id == doc_uuid, Document.knowledge_base_id == kb.id).first()
    if doc is None:
        raise HTTPException(404, "文档不存在")
    original = stored_original(doc.file_path)
    if original is None:
        raise HTTPException(404, "原文件未保留或已被旧版本清理，请重新上传后下载")
    return FileResponse(str(original), filename=doc.filename,
                        media_type="application/octet-stream", headers={"X-Content-Type-Options": "nosniff"})


@router.post("/{kb_id}/search")
async def search_knowledge_base(kb_id: str, request: KnowledgeSearchRequest,
                                current_user: User = Depends(get_current_user_required),
                                db: Session = Depends(get_db)):
    kb = owned_kb(db, current_user, kb_id)
    ensure_collection_is_exclusive(db, kb)
    query = request.query.strip()
    if not query:
        raise HTTPException(422, "请输入检索问题")
    from service.retrieval_service import search_chunks
    try:
        result = await run_in_threadpool(search_chunks, collection_for_name(kb.name), query,
                                        request.top_k, None, request.rerank)
    except Exception:
        raise HTTPException(503, "知识库检索服务暂不可用，请检查向量服务配置后重试")
    documents = db.query(Document).filter(Document.knowledge_base_id == kb.id).all()
    by_id = {str(doc.id): doc for doc in documents if doc.status == "completed"}
    modern_ids = {str(identity) for (identity,) in db.query(DocumentChunkProvenance.document_id).filter(
        DocumentChunkProvenance.document_id.in_([doc.id for doc in documents])).distinct().all()}
    by_legacy_id = {}
    for doc in documents:
        if doc.status == "completed" and str(doc.id) not in modern_ids:
            # Ambiguous historic duplicate names must not be mapped to an
            # arbitrary document; UUID-based new vectors have no ambiguity.
            key = hashlib.md5(doc.filename.encode()).hexdigest()
            if key in by_legacy_id:
                by_legacy_id[key] = None
            else:
                by_legacy_id[key] = doc
    enriched = enrich_chunks(db, collection_for_name(kb.name), result["results"], kb.id)
    rows = []
    for chunk in enriched:
        doc = by_id.get(chunk.get("document_id") or chunk.get("doc_id")) or by_legacy_id.get(chunk.get("doc_id"))
        if doc is None:
            continue  # No unowned or orphan vector metadata is returned.
        available = stored_original(doc.file_path) is not None
        rows.append({"chunk_id": chunk.get("id"), "document_id": str(doc.id),
                     "document_name": doc.filename, "content": chunk.get("content", ""),
                     "score": chunk.get("score", 0), "rerank_score": chunk.get("rerank_score"),
                     "chunk_index": chunk.get("chunk_index", 0), "download_available": available,
                     "document_version": chunk.get("document_version"),
                     "locators": chunk.get("locators", []), "assets": chunk.get("assets", []),
                     "evidence_id": chunk.get("evidence_id"), "content_hash": chunk.get("content_hash"),
                     "download_url": f"/knowledge-bases/{kb.id}/documents/{doc.id}/download" if available else None})
    return {"knowledge_base_id": str(kb.id), "query": query, "results": rows,
            "reranked": result["reranked"], "warning": result.get("warning")}


def owned_document(db, current_user, kb_id, doc_id):
    kb = owned_kb(db, current_user, kb_id)
    try:
        identity = UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "无效的文档ID格式")
    document = db.query(Document).filter(Document.id == identity, Document.knowledge_base_id == kb.id).first()
    if document is None:
        raise HTTPException(404, "文档不存在")
    return kb, document


@router.get("/{kb_id}/documents/{doc_id}/assets", response_model=DocumentAssetListResponse)
def list_document_assets(kb_id: str, doc_id: str,
                         current_user: User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    kb, document = owned_document(db, current_user, kb_id, doc_id)
    assets = db.query(DocumentAsset).filter_by(document_id=document.id).order_by(DocumentAsset.created_at, DocumentAsset.id).all()
    return {"document_id": str(document.id), "assets": [asset_response(asset, kb.id) for asset in assets]}


@router.get("/{kb_id}/documents/{doc_id}/assets/{asset_id}/download")
def download_document_asset(kb_id: str, doc_id: str, asset_id: str,
                            current_user: User = Depends(get_current_user_required), db: Session = Depends(get_db)):
    _, document = owned_document(db, current_user, kb_id, doc_id)
    asset = db.query(DocumentAsset).filter_by(id=asset_id, document_id=document.id).first()
    path = safe_asset_path(asset.file_path) if asset else None
    if path is None:
        raise HTTPException(404, "文献资产不存在或未保留")
    return FileResponse(str(path), filename=path.name, media_type=asset.media_type or "application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff"})
