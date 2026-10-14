# 数据服务审阅记录

审阅范围：用户提供的《雅意.md》P00 数据流、路由和安全限制、M02-T09 记忆实现，对照本项目知识库、Milvus/Embedding、数据库探索/Text2SQL、记忆、新闻代码。本文仅记录此子范围；真实服务端到端结果以总报告为准。

测试环境：WSL Ubuntu-24.04，`/home/ldj/anaconda3/envs/yayi_b/bin/python`。未安装依赖；未修改环境变量或用户原始数据；离线回归使用内存 SQLite 和 mock 外部服务。

|模块名|是否吻合|若不吻合代码是否完成修正|差异与证据|
|---|---|---|---|
|知识库创建、列表、文档上传和切片查看|部分吻合|已修复运行缺陷；接口命名差异保留|实际为 `/knowledge-bases` 和 `/{kb_id}/documents`，不是文档 `/knowledge/create`、`/knowledge/upload`。上传解析、1024维向量和PG元数据链路存在。原中文KB名称无法成为Milvus集合名，现统一映射为稳定ASCII名称，保留既有合法英文集合名。|
|知识库文件处理和上传限制|原不吻合，修正后基础文本流程吻合|是|原异步后台函数内部同步调用DocMind并轮询，阻塞事件循环；改同步BackgroundTask在线程池执行。新增唯一临时路径、路径分隔符清理、流式100MB上限和超限文件清理；TXT/MD/代码及文本数据文件本地解码，二进制文档保留DocMind。|
|知识库重命名和删除|原不完整，运行缺陷已修复|是，保留历史布局|原改名只改PG导致切片失联，删除只删PG导致向量残留；现在同步重命名/删除Milvus。目标集合存在时拒绝覆盖；共享名称、处理中任务返回409以避免误删。旧文件名hash布局不迁移，新同名文档返回409，历史重复记录最后一条删除时再删向量。|
|知识库用户隔离|不完全吻合|否，已加防误删保护，未迁移历史数据|集合仍按规范化名称而非用户/KB UUID区分；旧同名KB可能共享向量。上传/改名/删除遇到共享名称会拒绝，读取和研究检索隔离仍需后续统一身份设计。|
|RAG向量检索|部分吻合|已修复中文集合名；研究链路修复由研究子审阅负责|`retrieval_service.py:17` 调用text-embedding-v4、Milvus COSINE，返回内容与score；默认Top5，并非文档Top10。独立`/knowledge/search`接口不存在。实际基础检索函数未接Cross-Encoder；另有旧聊天重排代码，不等同于所述统一知识库查询链路。|
|原文档链接和向量缓存|不吻合|否，属于未实现能力|处理后临时原文件删除，没有文档原文件下载接口；未实现文档内容hash缓存、重复向量化复用。新增同名拒绝是避免ID冲突，不应表述为向量缓存。|
|数据库表、Schema、分页查询|原主键查询不吻合，已修复|是|SQLAlchemy将`:table_name::regclass`错误解析为`table_nam`，异常被吞导致主键总为空；改`CAST(:table_name AS regclass)`。其他表、列、索引和分页代码存在。|
|Text2SQL生成和执行|部分吻合|已修复执行缺陷；设计差异保留|实际自然语言接口为`POST /database/text2sql`，`/database/query`接收原始SQL；路由使用qwen-plus，非文档qwen-max。Prompt中是三个行业表的静态Schema，非自动读取任意当前数据库Schema。返回表格数据和可视化建议。|
|SQL只读和100条上限|原不吻合，Text2SQL已吻合|是|原仅Prompt要求100条，代码fetchall无限制，`updated_at`被UPDATE子串误拒绝，断连会返回演示模拟数据。共享验证器改为单条SELECT/关键字边界/屏蔽字面量、执行使用PG只读事务、外层LIMIT强制限制；Text2SQL最大100条，手工SQL按既有API允许1—1000条；未连接返回明确错误。|
|记忆摘要、向量存储、按用户召回|原首次使用失效，已修复|是|原`milvus`懒加载属性没有在写入和查询前调用，首次使用无连接/集合；现初始化连接和专用集合。写入失败不再把未成功写入的ID保存为已写入ID。摘要、每个洞察、主题向量化及按用户过滤、Top3上下文构建代码存在。|
|记忆自动压缩、定期压缩与混合召回|不吻合|否，属于尚未接线/未实现能力|`MEMORY_TOKEN_THRESHOLD=10000`、`should_compress`仅定义，主对话没有自动调用；调度器只有每日资讯任务，无30分钟记忆任务。手工`/memories/create`存在。召回仅Milvus向量，无PG关键词+向量混合。95%压缩率/费用未实测，不能确认。|
|新闻列表、筛选、统计、定时采集|基本吻合，有接口差异|无需运行修复；部分能力依赖外部API|`news_router.py:40`列表，行业/分类筛选、分页、统计和每日12点调度代码存在；文档`GET /news/:news_id`未实现。实际额外支持招投标。Bocha和招投标API是否有额度不能由mock认定。|
|普通聊天多轮历史连续性|原不吻合，已修复|是|三个completion入口遇到PG已有而Redis未建立的session_id时，原先另建随机Redis ID，前端下一轮仍用PG ID，导致不断新建并丢失上下文。现创建Redis会话时复用请求ID，第二轮沿用同一历史；无ID请求仍保持原有无状态行为。|

## 本次最小改动

- `backend/app/service/database_explorer.py`：修复主键参数绑定；查询走有界只读连接。
- `backend/app/service/sql_safety.py`：新增两个SQL入口共用的单语句SELECT验证、外层LIMIT、PG只读连接辅助函数。
- `backend/app/service/text2sql_service.py`：使用共享SQL验证/执行限制；断连不伪装为查询成功。
- `backend/app/service/memory_service.py`：首次向量写入/读取/删除触发连接与集合初始化；失败插入返回空ID列表；连接失败召回平稳降级。
- `backend/app/service/milvus_service.py`：中文等非法集合名稳定归一化；文件名和doc_id过滤表达式用JSON转义；增加拒绝覆盖的集合重命名方法。
- `backend/app/router/knowledge_router.py`：后台同步任务、受限唯一临时文件上传、知识库改名/文档删除/KB删除同步向量、防共享集合误删与处理中竞态、拒绝新同名文件。
- `backend/app/service/docmind_service.py`：已有文本类型本地解析；末块不重复追加尾部重叠片；校验不前进的分块参数和失败向量批次；保留DocMind HTTP200中的业务失败code，关闭上传句柄，设置请求超时。
- `backend/app/service/chat_service.py`：旧聊天RAG重排按node_id恢复分数与原文对应关系，避免将重排后第一名分数误赋给输入第一条文档；生成Prompt兼容仅有`content`的政策文档，修复重排降级后的`content_with_weight` KeyError，保持前端引用字段不变。
- `backend/app/service/session_service.py`、`backend/app/router/chat_router.py`：`create_session`增加可选现有ID，三个completion入口复用请求PG会话ID建立Redis历史；旧的无参数创建仍生成UUID。

## 验证结果

运行命令（项目根目录）：

```bash
cd backend
/home/ldj/anaconda3/envs/yayi_b/bin/python ../audit/test_data_regressions.py
```

23项全部通过。覆盖：无外部API的TXT解析/embedding/Milvus接口链路，失败embedding不写向量，中文集合稳定映射与引号文件名，改名保留旧数据且拒绝覆盖，共享KB保护，超限上传413与临时文件清理，SQL实际内存数据库执行/现有大LIMIT与子查询LIMIT不可绕过上限/正常字段字面量/拒绝写操作和多语句/断连返回错误/主键正确绑定，记忆首次连接/写入失败ID/召回降级，重排后分数始终归属原文，DocMind业务错误保留与文件句柄关闭，以及旧聊天v2/v3非空政策引用在重排降级后仍输出回答、原引用字段和结束SSE。

新增多轮会话测试使用真实SessionService逻辑与内存Redis替身，覆盖三个completion入口首次复用PG ID、第二轮不重复创建、第二轮模型Prompt包含第一轮对话、无ID请求兼容，以及旧无参数创建的随机UUID兼容。

政策文档兼容测试先在修改前复现了两个路由的`event: error / 'content_with_weight'`，随后用兼容内容读取修复。正常重排路径会填充该字段，所以该缺陷确切触发于重排降级等返回原始政策文档的路径，不能表述为所有知识库命中都必然失败。

这些测试证明所覆盖代码路径与修复回归正确，不证明远端LLM、DocMind、Bocha可用，也不是并发性能测试。运行时只有既有Pydantic配置弃用提示，不影响测试通过。

## 保留问题

1. 旧API `/documents/list`、`/documents/delete`、`/documents/retrieve`仍对接RAGFlow式远端，而`/documents/upload`改为DocMind/Milvus；这组历史接口存储链路不一致。当前知识库页面使用`/knowledge-bases`，未擅自替换旧接口协议。
2. 记忆向量存储失败仍保留PG摘要；修复保证不伪造向量ID，但没有新增补偿队列。删除记忆时向量服务不可用仍可能残留向量，需后续事务/重试策略。
3. SQL只读保护避免修改业务表，但数据库探索目前没有数据表白名单/行级权限；登录用户仍能查询系统表。不能把该原型认定为生产级多租户数据权限系统。
4. 新闻采集实现可能在外部API无结果时返回`success=True`并附errors；需要结合collected/errors判断，不应只看HTTP200。并未进行大量真实采集。
5. 归一化集合名仍继承旧逻辑对名称的小写/空格替换。跨用户同名历史集合不自动迁移，本次操作保护会提示409。

## 补充真实服务探针（2026-09-21）

脚本：`audit/live_vector_docmind_probe.py`；结果：`audit/live_vector_docmind_results.json`。

Milvus集成9项全部通过：固定1024维单位向量写入唯一中文临时知识库、COSINE查询命中（score=1）、带引号中文文件名查询、中文KB改名后切片保留、按文档删除向量、删除KB集合；独立临时记忆集合真实写入两个不同用户的向量、查询只命中指定用户；最终确认全部临时集合清理。测试使用**人工固定向量**，不是DashScope真实embedding，不能证明语义质量或付费Embedding服务可用。未操作用户集合或PostgreSQL用户数据。

DocMind仅额外提交一次不含用户信息的小合成PDF，返回HTTP200，`SubmitDocParserJobResponseBody.code=DocMindServiceNotOpen`，`message=You have not open the docMind service.`，`data=None`。已确认本机SDK响应`data`为有`.id`属性的模型，原取ID路径无误；失败根因是账号尚未开通DocMind服务，而原代码忽略了HTTP200响应中的业务错误。已修正上传状态为明确“DocMind服务尚未开通”，没有修改账号、开通服务或充值。

主流程真实Embedding请求另返回`AllocationQuota.FreeTierOnly`（免费额度耗尽且仅使用免费额度），所以真实文本知识库向量化和真实记忆语义召回仍被外部账户配置阻断。这与上述本地Milvus存储/检索成功应分开记录。
