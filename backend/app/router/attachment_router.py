
"""聊天附件路由"""
import os
import tempfile
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks, Form
from sqlalchemy.orm import Session

from core.database import get_db
from models.chat import ChatAttachment, ChatSession
from models.user import User
from router.auth_router import get_current_user_required
from schemas.chat import AttachmentResponse, AttachmentListResponse

router = APIRouter(prefix="/attachments", tags=["聊天附件"])

# 文件上传目录
UPLOAD_DIR = "/tmp/chat_attachments"
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_UPLOAD_SIZE = 100 * 1024 * 1024
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}


def extract_with_docmind(file_path, filename):
    """OCR/binary parsing uses the configured DocMind account, without indexing."""
    from service.docmind_service import DocMindService
    service = DocMindService()
    converted = None
    try:
        # DocMind does not list WebP as an input format; convert it locally.
        if get_file_extension(filename) == '.webp':
            from PIL import Image
            with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix='.png', delete=False) as out:
                converted = out.name
            with Image.open(file_path) as image:
                image.convert('RGB').save(converted, 'PNG')
            file_path, filename = converted, Path(filename).stem + '.png'
        task_id = service.submit_job(file_path, filename)
        if not task_id:
            raise ValueError(service.last_error or "DocMind文档提交失败")
        if not service.wait_for_completion(task_id):
            raise ValueError("DocMind解析失败或超时，请稍后重试")
        content = service.collect_all_results(task_id)
        if not content.strip():
            raise ValueError(service.last_error or "DocMind已完成任务，但未返回可识别正文")
        return content
    finally:
        if converted:
            Path(converted).unlink(missing_ok=True)

# 支持的文件类型
ALLOWED_EXTENSIONS = {
    # 文档类型
    '.pdf', '.docx', '.doc', '.txt', '.md', '.html', '.xlsx', '.xls', '.pptx', '.ppt',
    # 图片类型
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
    # 代码类型
    '.py', '.js', '.ts', '.json', '.yaml', '.yml', '.xml', '.csv',
}


def get_file_extension(filename: str) -> str:
    """获取文件扩展名"""
    return os.path.splitext(filename)[1].lower()


def attachment_to_response(att: ChatAttachment) -> AttachmentResponse:
    """将附件模型转换为响应"""
    return AttachmentResponse(
        id=str(att.id),
        session_id=str(att.session_id),
        message_id=str(att.message_id) if att.message_id else None,
        filename=att.filename,
        file_type=att.file_type,
        file_size=att.file_size,
        status=att.status,
        error_message=att.error_message,
        created_at=att.created_at,
    )


def process_attachment(attachment_id: str, file_path: str, db_session_factory):
    """后台处理附件（提取文本内容）"""
    import logging
    logger = logging.getLogger("AttachmentProcessor")

    db = db_session_factory()
    try:
        att = db.query(ChatAttachment).filter(ChatAttachment.id == attachment_id).first()
        if not att:
            return

        att.status = "processing"
        db.commit()

        try:
            content_text = ""
            ext = get_file_extension(att.filename)

            # Text and common Office formats are read locally; OCR uses DocMind.
            if ext in {'.txt', '.md', '.py', '.js', '.ts', '.json', '.yaml', '.yml', '.xml', '.csv', '.html'}:
                # 直接读取文本文件
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content_text = f.read()
            elif ext == '.pdf':
                from PyPDF2 import PdfReader
                try:
                    with open(file_path, 'rb') as source:
                        content_text = '\n'.join(page.extract_text() or '' for page in PdfReader(source).pages)
                except Exception:
                    content_text = ''
                if not content_text.strip():
                    content_text = extract_with_docmind(file_path, att.filename)
            elif ext == '.docx':
                from docx import Document
                document = Document(file_path)
                parts = [paragraph.text for paragraph in document.paragraphs]
                parts.extend('\t'.join(cell.text for cell in row.cells)
                             for table in document.tables for row in table.rows)
                content_text = '\n'.join(parts)
            elif ext == '.xlsx':
                from openpyxl import load_workbook
                workbook = load_workbook(file_path, read_only=True, data_only=True)
                try:
                    content_text = '\n'.join(
                        '\t'.join('' if value is None else str(value) for value in row)
                        for sheet in workbook for row in sheet.iter_rows(values_only=True))
                finally:
                    workbook.close()
            elif ext in IMAGE_EXTENSIONS | {'.doc', '.xls', '.ppt', '.pptx'}:
                content_text = extract_with_docmind(file_path, att.filename)
            else:
                raise ValueError(f"当前尚不支持提取 {ext} 附件正文，请转换为文本、PDF、DOCX 或 XLSX")

            if not content_text.strip():
                raise ValueError("未提取到正文，请检查文件内容或解析服务返回结果")

            # 限制内容长度
            if len(content_text) > 50000:
                content_text = content_text[:50000] + "\n...[内容已截断]"

            att.content_text = content_text
            att.status = "completed"
            att.error_message = None

        except Exception as e:
            logger.error(f"处理附件失败: {e}")
            att.status = "failed"
            att.error_message = str(e)

        db.commit()

    except Exception as e:
        logger.error(f"附件处理异常: {e}")
    finally:
        db.close()


@router.post("", response_model=AttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: str = Form(...),
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """上传聊天附件"""
    # 解析 session_id
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的会话ID格式"
        )

    # 验证会话存在
    session = db.query(ChatSession).filter(ChatSession.id == session_uuid, ChatSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )

    # 验证文件类型
    filename = os.path.basename((file.filename or '').replace('\\', '/'))
    ext = get_file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {ext}，支持的类型: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Generated path and streaming size cap, independent of the client filename.
    file_path = None
    file_size = 0
    size_limit = min(MAX_UPLOAD_SIZE, 20 * 1024 * 1024) if ext in IMAGE_EXTENSIONS else MAX_UPLOAD_SIZE
    try:
        with tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=ext, delete=False) as buffer:
            file_path = buffer.name
            while chunk := await file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > size_limit:
                    raise HTTPException(413, "图片最大20MB，其他附件最大100MB")
                buffer.write(chunk)
    except HTTPException:
        if file_path:
            Path(file_path).unlink(missing_ok=True)
        raise
    except Exception as e:
        if file_path:
            Path(file_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件保存失败: {str(e)}"
        )

    # 创建附件记录
    att = ChatAttachment(
        session_id=session_uuid,
        user_id=current_user.id,
        filename=filename,
        file_type=ext[1:] if ext else "unknown",
        file_size=file_size,
        file_path=file_path,
        status="pending",
    )
    db.add(att)
    db.commit()
    db.refresh(att)

    # 后台处理附件
    from core.database import SessionLocal
    background_tasks.add_task(
        process_attachment,
        str(att.id),
        file_path,
        SessionLocal
    )

    return attachment_to_response(att)


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """获取附件详情"""
    try:
        att_uuid = UUID(attachment_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的附件ID格式"
        )

    att = db.query(ChatAttachment).filter(ChatAttachment.id == att_uuid, ChatAttachment.user_id == current_user.id).first()
    if not att:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="附件不存在"
        )

    return attachment_to_response(att)


@router.get("/session/{session_id}", response_model=AttachmentListResponse)
async def get_session_attachments(
    session_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """获取会话的所有附件"""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的会话ID格式"
        )

    # 验证会话存在
    session = db.query(ChatSession).filter(ChatSession.id == session_uuid, ChatSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )

    attachments = db.query(ChatAttachment).filter(
        ChatAttachment.session_id == session_uuid
    ).order_by(ChatAttachment.created_at.desc()).all()

    return AttachmentListResponse(
        attachments=[attachment_to_response(att) for att in attachments],
        total=len(attachments),
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """删除附件"""
    try:
        att_uuid = UUID(attachment_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的附件ID格式"
        )

    att = db.query(ChatAttachment).filter(ChatAttachment.id == att_uuid, ChatAttachment.user_id == current_user.id).first()
    if not att:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="附件不存在"
        )

    if att.status in ('pending', 'processing'):
        raise HTTPException(409, "附件正在处理中，请处理结束后重试")
    # 删除文件
    if att.file_path and os.path.exists(att.file_path):
        try:
            os.remove(att.file_path)
        except Exception:
            pass  # 忽略文件删除错误

    db.delete(att)
    db.commit()
    return None
