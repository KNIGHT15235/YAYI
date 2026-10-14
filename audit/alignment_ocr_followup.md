# 图片 OCR 空正文专项复核（2026-09-21）

## 结论

本次 `scan.png` 空正文来自云端已完成任务的空解析结果，不是客户端漏读了已有正文。保持同一合成图像内容，以官方 VLM OCR 参数组合提交 **一次** 新任务后，成功提取 20 字符，并包含合成标记 `YAYI`、`7342`。

已在 `backend/app/service/docmind_service.py` 中对 jpg/jpeg/png/bmp/gif 图片启用该参数组合；PDF 等其他格式保持原参数。未改 `attachment_router.py`，未重启后端。旧文件已备份到 `audit/alignment-before/backend/app/service/docmind_service.py`。

## 证据

1. 读取原有合成测试任务的 `query_status` 和 `get_result`，未重复提交：云端 `Status=success`，但 `ParagraphCount`、`ImageCount`、`PageCountEstimate`、`NumberOfSuccessfulParsing`、`Tokens` 均为 0；`OutputFormatResult=[]`，实际 `Data={"layouts":[]}`。修正后的解析器同样返回空串，并给出空正文诊断；没有伪造识别结果。脱敏记录为 `audit/docmind_existing_ocr_result.json`。
2. 依照 `audit/smoke_alignment_live.py` 相同代码重建 `audit/ocr-synthetic.png` 并人工视觉检查：1000×220 白底图，42 号 DejaVuSans，文本完整且清晰。不是空白图片或字体缺失。
3. 对这一张合成图片使用 `LlmEnhancement=true`、`EnhancementMode=VLM`、`NeedHeaderFooter=true` 提交一次小任务，云端成功完成，返回 20 字符正文，包含 `7342`。记录为 `audit/ocr_vlm_probe_result.json`、`audit/ocr_vlm_probe.log`。测试仅使用合成内容，没有上传用户文件。
4. 官方资料明确支持 PNG/JPG 等图片；VLM 参数用于多模态版面分析和 OCR，`LayoutNum` 从 0 开始。此次成功验证的是参数组合，未通过额外多次提交将结果归因于某一个单独参数。[阿里云文档解析（大模型版）说明](https://help.aliyun.com/zh/document-mind/developer-reference/document-parsing-large-model-version)

## 改动范围

- 图片扩展名统一小写；jpg/jpeg/png/bmp/gif 默认使用上述 OCR 参数。WebP 仍由现有附件路由转 PNG 后调用本服务。
- 新配置 `DOCMIND_IMAGE_VLM_ENABLED` 默认 `true`。设为 `false` 可恢复无 VLM 的图片请求；此时清晰图片也可能出现本次观察到的空结果。没有修改现有 `.env`。
- VLM 可能增加处理时间和每页费用，具体由云端计费决定；没有承诺免费或固定成本。非图片不自动启用 VLM。
- `collect_all_results` 兼容 SDK 对象、`to_map()` 结果、JSON 字符串及 `Data` 包装；优先读取完整 `markdownContent`，其次 `text`、`llmResult`，缺失时读取官方结构中的 `blocks`/`cells` 文本。每块只采用一种表示，避免重复正文；分页仍按返回布局块数推进。
- 云端空布局保持空结果，并设置 `last_error`；异常输出只保留错误类型/代码，不打印签名 URL。

## 回归结果

- `audit/test_docmind_result_shapes.py`：**11/11 通过**，全部 mock；覆盖 SDK/字典/JSON、大小写字段、嵌套 OCR 块、Markdown 去重、VLM 字段、分页、空结果、无效 JSON、图片参数开关与 PDF 参数隔离。
- `audit/test_data_regressions.py`：**23/23 通过**，结果见 `audit/docmind_data_regressions.log`。
- 真实小图片任务：成功，包含合成标记；新提交数量严格为 1。
- 后端重启后的 HTTP 附件上传完整链路由主任务统一复验，不能将本次直接服务调用结果冒称已完成 HTTP 重启验收。

## 文档追加建议

> 图片附件通过 DocMind 解析。默认启用图片 VLM OCR 增强（`DOCMIND_IMAGE_VLM_ENABLED=true`），WebP 先转 PNG；其他文档类型保持原解析设置。云端状态 success 仍需返回有效正文才认定附件解析完成，空结果会标记失败并展示原因。VLM 增强可能增加处理时间和每页费用，实际识别质量依赖图像和云服务。当前已用一张清晰合成图片验证成功，不保证所有扫描件都可准确识别。
