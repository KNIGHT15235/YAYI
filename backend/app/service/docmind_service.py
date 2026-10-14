
"""DocMind 文档智能解析服务"""
import os
import time
import hashlib
import json
from typing import List, Dict, Any, Optional
from alibabacloud_docmind_api20220711.client import Client as DocMindClient
from alibabacloud_docmind_api20220711 import models as docmind_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

from service.embedding_service import generate_embedding
from service.milvus_service import get_milvus_service
from service.document_assets import (normalize_layouts, chunk_text_with_offsets,
                                     stable_chunk_id, build_provenance, digest, remove_asset_files)


class DocMindService:
    """DocMind 文档解析服务"""

    def __init__(self):
        self.access_key_id = os.getenv("DOCMIND_ACCESS_KEY_ID")
        self.access_key_secret = os.getenv("DOCMIND_ACCESS_KEY_SECRET")
        self.endpoint = "docmind-api.cn-hangzhou.aliyuncs.com"
        self.client = self._create_client()
        self.last_error: Optional[str] = None

    def _create_client(self) -> DocMindClient:
        """创建 DocMind 客户端"""
        config = open_api_models.Config(
            access_key_id=self.access_key_id,
            access_key_secret=self.access_key_secret,
        )
        config.endpoint = self.endpoint
        return DocMindClient(config)

    def submit_job(self, file_path: str, file_name: str) -> Optional[str]:
        """
        提交文档解析任务

        Args:
            file_path: 文件路径
            file_name: 文件名

        Returns:
            任务 ID，失败返回 None
        """
        self.last_error = None
        try:
            with open(file_path, "rb") as source:
                extension = os.path.splitext(file_name)[1].lower().lstrip(".")
                image_options = {}
                if extension in {"jpg", "jpeg", "png", "bmp", "gif"} and os.getenv("DOCMIND_IMAGE_VLM_ENABLED", "true").lower() in {"true", "1", "yes", "on"}:
                    # Explicitly enable the documented OCR/visual-layout chain
                    # for images. Plain parsing can succeed with empty layouts.
                    # VLM is restricted to images because it affects latency/cost.
                    image_options = {"llm_enhancement": True, "enhancement_mode": "VLM", "need_header_footer": True}
                request = docmind_models.SubmitDocParserJobAdvanceRequest(
                    file_url_object=source,
                    file_name=file_name,
                    file_name_extension=extension or None,
                    output_format=["visualLayoutInfo"],
                    **image_options,
                )
                runtime = util_models.RuntimeOptions(connect_timeout=10000, read_timeout=30000)
                response = self.client.submit_doc_parser_job_advance(request, runtime)

            if response.body and response.body.data and response.body.data.id:
                task_id = response.body.data.id
                print(f"任务已提交，任务ID: {task_id}")
                return task_id
            code = getattr(response.body, "code", None) or "MissingTaskId"
            if code == "DocMindServiceNotOpen":
                self.last_error = "DocMind 服务尚未开通（DocMindServiceNotOpen）"
            else:
                self.last_error = f"DocMind 文档提交失败（{code}）"
            print(self.last_error)
            return None

        except Exception as e:
            # SDK exception text may contain signed upload URLs; retain only
            # the diagnostic code and never include request credentials.
            code = getattr(e, "code", None) or type(e).__name__
            self.last_error = f"DocMind 文档提交失败（{code}）"
            print(self.last_error)
            return None

    def query_status(self, task_id: str) -> Optional[Dict]:
        """
        查询任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态信息
        """
        try:
            request = docmind_models.QueryDocParserStatusRequest(id=task_id)
            response = self.client.query_doc_parser_status(request)
            if response.body and response.body.data:
                return response.body.data.to_map()
            return None
        except Exception as e:
            print(f"查询状态失败: {e}")
            return None

    def wait_for_completion(self, task_id: str, poll_interval: int = 5, max_wait: int = 300) -> bool:
        """
        等待任务完成

        Args:
            task_id: 任务ID
            poll_interval: 轮询间隔（秒）
            max_wait: 最大等待时间（秒）

        Returns:
            任务是否成功完成
        """
        print("开始轮询任务状态...")
        start_time = time.time()

        while time.time() - start_time < max_wait:
            status_data = self.query_status(task_id)
            if not status_data:
                print("查询状态失败")
                return False

            status = status_data.get('Status', '').lower()
            print(f"当前状态: {status}")

            if status == 'success':
                print("任务已成功完成")
                return True
            elif status == 'failed':
                print("任务执行失败")
                return False
            else:
                # 任务仍在处理中
                time.sleep(poll_interval)

        print("等待超时")
        return False

    def get_result(self, task_id: str, layout_num: int = 0, layout_step_size: int = 10) -> Optional[Any]:
        """
        获取文档解析结果（支持增量获取）

        Args:
            task_id: 任务ID
            layout_num: 起始布局编号
            layout_step_size: 步长

        Returns:
            解析结果
        """
        try:
            request = docmind_models.GetDocParserResultRequest(
                id=task_id,
                layout_step_size=layout_step_size,
                layout_num=layout_num
            )
            response = self.client.get_doc_parser_result(request)
            return response.body.data if response.body and response.body.data else None
        except Exception as e:
            code = getattr(e, "code", None) or type(e).__name__
            self.last_error = f"DocMind结果获取失败（{code}）"
            print(self.last_error)
            return None

    @staticmethod
    def _result_value(value, *names):
        """Read either an SDK model or its dictionary/JSON representation."""
        for name in names:
            item = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
            if item is not None and item != "":
                return item
        return None

    @classmethod
    def _result_payload(cls, value):
        for _ in range(4):
            if hasattr(value, "to_map"):
                value = value.to_map()
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    return {}
            wrapped = cls._result_value(value, "Data", "data")
            if wrapped is None:
                return value
            value = wrapped
        return value

    @classmethod
    def _layout_text(cls, value, depth=0):
        if depth > 6:
            return ""
        # Prefer one complete representation, avoiding duplicate copies of the
        # same OCR text in markdown, text, and nested line blocks.
        for aliases in (("markdown_content", "markdownContent", "MarkdownContent"),
                        ("text", "Text"), ("llm_result", "llmResult", "LlmResult")):
            content = cls._result_value(value, *aliases)
            if isinstance(content, str) and content.strip():
                return content.strip()
        blocks = cls._result_value(value, "blocks", "Blocks", "cells", "Cells", "layouts", "Layouts")
        if isinstance(blocks, list):
            return "\n".join(text for block in blocks if (text := cls._layout_text(block, depth + 1)))
        return ""

    def collect_structured_results(self, task_id: str, layout_step_size: int = 10) -> Dict[str, Any]:
        """
        收集所有解析结果

        Args:
            task_id: 任务ID
            layout_step_size: 步长

        Returns:
            完整的文本内容
        """
        all_layouts = []
        self.last_error = None
        layout_num = 0

        while True:
            result_data = self.get_result(task_id, layout_num, layout_step_size)
            if not result_data:
                break

            result_data = self._result_payload(result_data)
            layouts = self._result_value(result_data, "layouts", "Layouts")

            if not layouts:
                if layout_num == 0:
                    if self._layout_text(result_data):
                        all_layouts.append(result_data)
                break
            if not isinstance(layouts, list):
                self.last_error = "DocMind返回的布局格式无效"
                break

            print(f"获取到 {len(layouts)} 个布局块 (从 {layout_num} 开始)")

            all_layouts.extend(layouts)

            # 更新下次获取的起始位置
            layout_num += len(layouts)

            # 如果获取到的数量小于步长，说明已经获取完所有内容
            if len(layouts) < layout_step_size:
                break

        normalized = normalize_layouts(all_layouts, self._layout_text)
        if not normalized["text"] and not self.last_error:
            self.last_error = "DocMind任务未返回可识别正文（布局为空或不含文字）；请检查图片清晰度或解析服务结果"
        # Never index a partial document after a pagination/provider failure.
        normalized["error"] = self.last_error
        return normalized

    def collect_all_results(self, task_id: str, layout_step_size: int = 10) -> str:
        """Compatibility wrapper for attachments and existing text callers."""
        return self.collect_structured_results(task_id, layout_step_size)["text"]


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    将文本切分成块

    Args:
        text: 原始文本
        chunk_size: 每块大小
        overlap: 重叠大小

    Returns:
        文本块列表
    """
    if not text:
        return []
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size")

    return [chunk["content"] for chunk in chunk_text_with_offsets(text, chunk_size, overlap)]


def process_document_with_docmind(
    file_path: str,
    file_name: str,
    index_name: str,
    chunk_size: int = 500,
    document_id: Optional[str] = None,
    existing_task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用 DocMind 处理文档

    Args:
        file_path: 文件路径
        file_name: 文件名
        index_name: ES 索引名
        chunk_size: 切片大小

    Returns:
        处理结果
    """
    result = {
        "success": False,
        "message": "",
        "document_count": 0,
    }
    generated_assets = []
    vectors_started = False

    try:
        print(f"开始处理文档: {file_name}")

        with open(file_path, "rb") as source:
            document_version = hashlib.file_digest(source, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else digest(source.read())
        text_extensions = {".txt", ".md", ".html", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".xml", ".csv"}
        if os.path.splitext(file_name)[1].lower() in text_extensions:
            # Plain text needs no paid document-parser job. Keep the same
            # chunk/embedding/storage pipeline as binary document uploads.
            with open(file_path, "rb") as source:
                raw = source.read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
            parsed = {"text": text, "blocks": [], "assets": []}
        else:
            service = DocMindService()
            task_id = existing_task_id or service.submit_job(file_path, file_name)
            if not task_id:
                result["message"] = service.last_error or "文档提交失败"
                return result
            if not service.wait_for_completion(task_id):
                result["message"] = "文档解析任务失败或超时"
                return result
            parsed = service.collect_structured_results(task_id)
            if parsed.get("error"):
                result["message"] = parsed["error"]
                return result
            text = parsed["text"]

        if not text or not text.strip():
            result["message"] = "文档内容为空"
            print(result["message"])
            return result

        print(f"解析到文本长度: {len(text)}")

        # 4. 文本切分
        chunk_records = chunk_text_with_offsets(text, chunk_size=chunk_size,
                                               overlap=min(50, chunk_size - 1), blocks=parsed.get("assets"))
        chunks = [row["content"] for row in chunk_records]

        if not chunks:
            result["message"] = "文档切分失败"
            print(result["message"])
            return result

        print(f"文档切分完成，共 {len(chunks)} 个切片")

        # 5. 生成向量嵌入
        print("开始生成向量嵌入...")
        embeddings = generate_embedding(chunks)

        if not embeddings:
            result["message"] = "向量生成失败: 返回为空"
            print(result["message"])
            return result

        if len(embeddings) != len(chunks):
            result["message"] = f"向量生成失败: 数量不匹配 ({len(embeddings)} vs {len(chunks)})"
            print(result["message"])
            return result

        if any(not vector or len(vector) != 1024 for vector in embeddings):
            result["message"] = "向量生成失败: 存在缺失或维度不为 1024 的向量"
            return result

        print(f"向量生成完成，维度: {len(embeddings[0])}")

        # 6. 构建 Milvus 文档
        # Legacy callers retain their historic IDs; uploads always supply the
        # real Document UUID, making same-name files independent identities.
        doc_id = str(document_id) if document_id else hashlib.md5(file_name.encode()).hexdigest()
        documents = []

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = stable_chunk_id(doc_id, document_version, i) if document_id else hashlib.md5(f"{file_name}_{i}_{chunk[:50]}".encode()).hexdigest()

            doc = {
                "id": chunk_id,
                "doc_id": doc_id,
                "kb_id": index_name,
                "filename": file_name,
                "content": chunk,
                "chunk_index": i,
                "vector": embedding,
            }
            documents.append(doc)

        # 7. 插入 Milvus
        print(f"开始插入 Milvus，集合: {index_name}")
        milvus = get_milvus_service()
        vectors_started = True
        milvus.insert_documents(index_name, documents)

        if document_id:
            try:
                generated_assets, provenance, warnings = build_provenance(doc_id, document_version, parsed, chunk_records, file_path, asset_sink=generated_assets)
            except Exception:
                milvus.delete_by_doc_id(index_name, doc_id)
                raise
            result.update(document_id=doc_id, document_version=document_version,
                          assets=generated_assets, provenance=provenance, warnings=warnings)

        result["success"] = True
        result["message"] = f"成功处理 {len(documents)} 个切片"
        result["document_count"] = len(documents)

        print(f"文档处理完成: {result['message']}")

    except Exception as e:
        remove_asset_files([asset["file_path"] for asset in generated_assets])
        if vectors_started and document_id:
            try:
                milvus.delete_by_doc_id(index_name, str(document_id))
            except Exception:
                pass
        result["message"] = f"处理失败: {str(e)}"
        print(f"文档处理异常: {e}")
        import traceback
        traceback.print_exc()

    return result
