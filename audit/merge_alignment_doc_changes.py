"""Finalize reviewed corrections against the immutable original line numbers."""
import json
from pathlib import Path

path = Path(__file__).with_name('alignment_doc_changes.json')
changes = json.loads(path.read_text(encoding='utf-8'))

def edit(start, end, reason, replacement, category='按实际代码改写'):
    global changes
    changes = [item for item in changes if item['end'] < start or item['start'] > end]
    changes.append(dict(start=start, end=end, reason=reason, replacement=replacement, category=category))

for item in changes:
    if item['start'] == 5:
        item['replacement'] = '文档更新时间：2026-09-22（代码对齐版；保留原文件不覆盖）'
    if item['start'] == 35:
        item['replacement'] = item['replacement'].replace('POST /cancel、', 'POST /cancel/{session_id}、')
    if item['start'] == 230 and 'Critic' not in item['replacement']:
        item['replacement'] += '\n\n    质量审核Critic绕过响应缓存；HTTP成功不代表五维评分已通过业务校验，审核及纠正请求均重新调用模型。'
    if item['start'] == 298:
        item['replacement'] = '**[M01-Q02] [为何混合使用DeepSeek和Qwen？]** 默认以deepseek-v3.2承担规划、数据分析、代码和写作，DeepScout与质量审核Critic使用qwen-plus。审核模型可通过CRITIC_MODEL独立配置；其切换不改变五维量表、加权公式和通过门槛。模型选择是工程配置，不保证固定质量或速度；费用以实际配置与服务商账单为准。'

edit(3,3,'项目原型身份以用户说明和当前仓库为准，不推断第三方产品归属', '项目 ID：01-YAYI雅意（当前仓库：industry_information_assistant 原型）')
edit(176,176,'说明实际取消标记和运行锁期限', '    - Redis保存5分钟取消标记；运行租约有效期120秒，每30秒续期。完整研究状态仍在PostgreSQL检查点中。')
edit(264,264,'新增真实鉴权限流与重复执行保护', '    研究限流：按已认证用户统计启动/恢复请求，每60秒最多10次；每用户同时最多一个研究，同一会话禁止重复执行。运行冲突返回409或429，协调服务不可用时返回503。', '已补齐代码')
edit(308,308,'说明检查点是阶段级恢复，不能保证中途工作零损失', '**[M01-Q07] [为何使用检查点？]** 每个阶段保存状态、UI和下一阶段。中断后可手动继续最近检查点；尚未完成阶段可能重新执行，已经提交的外部同步请求不一定能被强制终止。因此不能保证所有中途token与外部调用均可回收。')
edit(341,341,'同进程exec不能称为安全隔离', '**[M01-Q14] [受限代码执行机制如何工作？]**')
edit(394,410,'明确生产流程与保留实验代码边界', '## [M02-T01] [研究编排与状态管理]\n\n当前 `run()` 固定调用 `_run_simplified`；项目没有经过验收的双引擎切换开关。\n\n1. LangGraph实验实现：`_run_with_langgraph` 使用StateGraph和`graph.astream()`，按节点输出消息；分析节点仅调用Wizard，审核后支持修订，没有完整补检路径。其事件粒度、恢复行为和Agent组合尚未与生产流程做等价验收，不建议直接切换部署。', '未实现，改为明确边界')
edit(420,420,'实际取消检查为轮询且有同步线程边界', '    - 在阶段间以及等待Agent时约每0.5秒检查取消；关闭异步生成器会取消Agent协程并保存可恢复状态。已经运行的同步线程/SDK请求无法由此强制终止。')
edit(530,530,'搜索缓存已接Redis', '6. 网络搜索实现：`_execute_search()`调用Bocha API；Redis缓存900秒，键包含query、count、freshness，缓存不可用时直接搜索，调用通过异步流程执行。', '已补齐代码')
edit(554,554,'将已有深读函数接入实际研究路径并限制请求范围', '**[深度阅读]** 主流程在网络搜索后、分析前调用`deep_read_url()`。每次研究最多深读3个去重URL；仅允许公网HTTP(S)及80/443端口，校验DNS和每次重定向并固定连接IP。单页响应最多1MB，抓取约10秒、等待约12秒、含模型分析整体预算25秒，最多3次重定向。失败时保留搜索摘要继续。正文依下述三层方式提取。', '已补齐代码')
edit(566,566,'与Scout配置一致，不把max_tokens当完整性保证', '**[模型选择]** DeepScout使用qwen-plus，temperature=0.2；Agent基类请求默认max_tokens=16000，具体请求可覆盖。输出上限不能保证JSON完整或响应必然成功。')
edit(588,588,'纠正DataAnalyst模型及请求预算', '**[模型选择]** DataAnalyst使用deepseek-v3.2，数据提取与图谱分析temperature=0.2，图表配置temperature=0.3；Agent基类默认max_tokens=16000。')
edit(630,636,'限定执行器能力，不承诺系统级安全隔离', '3. `_execute_in_sandbox()`保留原方法名，但实际为同进程受限exec：检查模块与危险代码模式，设置绘图环境，捕获stdout/stderr，并在绘图锁内收集本次所有新建图形、转换Base64后关闭。\n\n    1. 仅开放pandas、numpy、matplotlib、seaborn等选定模块。\n\n    2. 禁止直接调用open、exec、eval、os、sys、subprocess等危险名称。\n\n    3. 检查requests、urllib、socket等直接网络调用；以上限制不能阻止所有间接文件/网络访问，不是进程、文件系统或网络隔离。', '未实现，改为明确边界')
edit(640,640,'字体设置不能保证宿主机有字体', '    5. 中文字体预设：配置候选字体；实际效果取决于运行环境安装的字体。')
edit(648,648,'纠正Wizard输出预算', '**[模型选择]** CodeWizard使用deepseek-v3.2，代码生成temperature=0.3，修复temperature=0.2；Agent基类默认max_tokens=16000。')
edit(785,785,'审核修订后的报告并说明实际截断范围', '3. `_review_content()`优先读取当前final_report，缺失时回退draft_sections；结合前20条事实、前15条数据和大纲调用模型审核。报告最多取8000字符，因此超长报告的尾部不属于本轮全文审核覆盖范围。')
edit(789,789,'权重计算已由程序落实，评分仍非事实核验', '**[质量评分机制]** 模型提供source_completeness、logical_rigor、objectivity、timeliness、completeness五个1—10分维度；程序验证后按0.3、0.3、0.2、0.1、0.1计算总分。忽略模型自报总分，缺失或非法分数不视为有效评分；该结果是辅助评估，不是独立事实核验。', '已补齐代码')
edit(793,793,'按当前生产路径阶段路由描述', '1. 当前asyncio流程由Critic更新phase决定后续：需要新证据进入补检，需要修改进入修订；不是仅依据未解决问题数量调用通用_should_revise。')
edit(797,797,'实际迭代默认和允许范围', '3. 默认最多3次审核迭代，接口允许1—5；达到上限输出警告并保留报告，不把达到上限当作质量通过。')
edit(799,799,'评分通过还需无严重问题', '4. 有效评分至少7分且没有critical/major问题时通过；否则在迭代预算内补检或修订，再次审核。达到上限时携带警告完成，用户仍需查看未解决问题。')
edit(813,813,'更正执行器安全表述', '**[Step4 CodeWizard—代码生成阶段]** 输入data_points，模型生成代码，清理后在同进程受限执行器中执行，收集本次新建图表并写入charts；输出code、code_result、chart事件。该执行器不是强隔离沙箱。')
edit(846,846,'实现新消息触发和统一token估算', '2. 短期记忆：消息存入ChatMessage后登记待处理会话，以cl100k_base估算未压缩文本token；默认达到10000时触发后台压缩。只登记启用后保存的新消息，不扫描所有历史会话。', '已补齐代码')
edit(848,848,'实现增量批次和失败处理，删除固定压缩率', '3. 记忆压缩：默认qwen-plus，每批最多30000字符，生成summary、key_insights、user_preferences和topics；保存消息ID及字符进度，只推进成功部分，尾部等待后续批次。没有95%的固定压缩率。', '已补齐代码')
edit(850,854,'补齐实际混合召回并纠正PG内容', '4. 长期记忆：当前用户范围内进行关键词与向量融合召回，按memory_id去重、经PostgreSQL再次核验归属后取Top-3构建上下文。\n\n    1. PostgreSQL存储结构化摘要、洞察、主题及来源进度；原始对话仍在消息表，不是复制进记忆表。关键词查询使用参数化SQL。\n\n    2. Milvus存储摘要、洞察与主题向量；向量不可用时关键词结果仍可用。使用排序融合，不把余弦分数与关键词分数直接相加。', '已补齐代码')
edit(860,864,'明确真实生命周期、容量和存储方式', '|存储位置|PostgreSQL消息与请求上下文|PostgreSQL摘要 + Milvus向量|\n|生命周期|会话消息持久保存，调用时选取预算内上下文|持久保存，受用户删除及存储策略影响|\n|容量限制|受消息条数与上下文token预算限制|受磁盘、数据库容量及成本限制|\n|访问方式|按预算组织最近消息|当前用户的关键词与向量融合召回|\n|内容|原始消息与本次上下文|摘要、洞察、主题、偏好和处理进度|')
edit(866,866,'补齐手动与自动入口，并明确重试/索引分离', '触发方式：界面“保存为记忆”、新消息达到token阈值、每30分钟检查已登记且有未处理消息的会话。三者共用增量压缩逻辑，以会话锁避免重复。摘要成功后单独提交向量索引任务；模型失败和索引失败分别有限重试，失败不伪装为完成。', '已补齐代码')
edit(924,924,'说明实际预算及费用边界', '1. 记忆总结：按来源消息进度组织未压缩内容，每批最多30000字符，调用模型并校验结构；成功摘要先保存再推进进度，失败按策略重试。没有单次0.05元的固定费用保证。')
edit(926,926,'使用稳定ID幂等upsert避免重复索引', '2. 记忆向量化：创建COSINE索引，为摘要、每条洞察及组合主题生成向量，使用基于memory_id的稳定ID进行Milvus upsert；索引失败保留PostgreSQL摘要并重试。', '已补齐代码')
edit(932,932,'修正方法名与实际混合检索步骤', '3. `MemoryService.retrieve_memories()`：查询当前用户关键词结果，同时按用户过滤检索Milvus；对结果进行排序融合，按memory_id去重并通过PostgreSQL再次验证归属后返回。', '已补齐代码')
edit(106,106,'标明实验代码省略导入与实现', '下面是实验节点的结构示意，省略了导入与实现，不能直接执行；真实流程以源码为准。节点内部调用对应Agent的process方法。')
edit(216,216,'统一执行器实际边界', 'SSE实时推送、阶段检查点机制、同进程受限代码执行器。')
edit(426,426,'TypedDict仅提供静态类型描述', '核心组件：ResearchState TypedDict提供共享状态的静态类型描述；运行时仍依赖显式校验，TypedDict本身不确保运行时类型安全。ResearchPhase定义阶段枚举。')
edit(480,480,'请求配置不能保证结构/质量', '**[模型选择]** ChiefArchitect使用deepseek-v3.2，temperature=0.3、max_tokens=16000；这些是请求配置，不保证输出结构完整或规划质量。')
edit(500,500,'启发式指纹不是语义向量去重', '**[职责]** 网络与本地知识库搜索、受预算约束的网页原文阅读、递归线索追踪、模型信源评级、数字/中文片段哈希启发式去重、假设证据累计、知识图谱与补充搜索。评级、指纹和证据计数都不构成独立事实核验。')
edit(512,512,'将交叉验证改为真实去重算法', '4. 事实去重：`_compute_fact_fingerprint()`提取数字和中文片段并计算哈希，`_is_duplicate_fact()`结合来源判断重复；这是启发式文本去重，不是语义向量匹配，也不能证明不同来源的事实互相独立或真实。')
edit(564,564,'纠正单条证据自动部分支持的描述', '**[假设状态]** `_update_hypothesis_status()`累计模型提取的支持/反驳证据；对应方向达到2条后更新supported/refuted。单条支持或反驳不会自动转为partially_supported，其他证据类型可能更新该状态。这是程序计数规则，不代表假设已被严格证实。')
edit(652,652,'统一代码执行风险边界', '**[执行限制]** 黑白名单检查直接危险操作并开放选定分析模块；同进程exec不能保证阻断所有间接文件或网络访问。强隔离仍需另建容器/进程执行环境。')
edit(725,727,'引用来源信息不能保证完整作者和日期', '2. 引用结构：Writer初始保存id、marker、source、url；后续结果可能补充title、link、content等展示字段。并非每条来源都有作者、日期或完整元信息。\n\n3. 前端按实际可用的标题、链接和来源展示引用，缺失字段不虚构。引用仍需用户核对原始出处。')
edit(789,789,'落实五维校验及真实模型异常降级', '**[质量评分机制]** 模型提供source_completeness、logical_rigor、objectivity、timeliness、completeness五个1—10分维度；程序验证后按0.3、0.3、0.2、0.1、0.1计算总分，忽略模型自报总分。非法或缺失评分仅纠正重试一次；仍失败则保留报告、清除旧评分，输出quality_score=null和quality_review_status=unconfirmed，提示“审核待确认”。不把非法分数截成满分。有效评分也仅为模型辅助评估，不是独立事实核验。', '已补齐代码')
edit(797,797,'区分修订次数与初始审核次数', '3. max_iterations默认3，接口允许1—5，限制修订循环次数；初始审核后仍可按预算修订并复审，不能把该参数当成所有审核调用总数。达到上限时输出警告并保留报告，不把达到上限当成质量通过。')
edit(819,819,'完成也可能附带质量待确认，示例不是实际API响应', '**[Step7 完成]** 有效评分至少7且无critical/major问题时通过；达到修订上限则附警告完成；审核纠正重试仍失败时保留报告并标为“审核待确认”。下方为虚构的内部状态示意，包含省略符，不是有效JSON或API响应。实际research_complete含type、facts_count、charts_count、iterations、references和quality_review_status等字段。')
edit(838,838,'不能仅凭总分判断修订', '**[修订流程]** 未通过审核时，在预算内选择补充检索或修订并再次审核；不能只用quality_score小于7判断是否需要修改。')
edit(850,854,'区分聊天Top3与搜索接口Top5', '4. 长期记忆：当前用户范围内进行关键词与向量融合召回，按memory_id去重、经PostgreSQL再次核验归属。聊天上下文默认取Top-3；`/memories/search`默认Top-5，可传1—20。\n\n    1. PostgreSQL存储结构化摘要、洞察、主题及来源进度；原始对话仍在消息表，不是复制进记忆表。关键词查询使用参数化SQL。\n\n    2. Milvus存储摘要、洞察与主题向量；向量不可用时关键词结果仍可用。使用排序融合，不把余弦分数与关键词分数直接相加。', '已补齐代码')
edit(866,866,'区分自动任务重试与手动错误提示', '触发方式：界面“保存为记忆”、新消息达到token阈值、每30分钟检查已登记且有未处理消息的会话。三者共用增量压缩逻辑，以会话锁避免重复。自动队列对摘要失败有限重试；手动模型失败返回503，用户可重新提交。摘要成功后单独提交向量索引任务，失败时保留摘要并重试索引，不伪装为完成。', '已补齐代码')
edit(868,868,'模型示例为字段节选', '**记忆数据模型**：以下是字段节选，省略导入与实现，不能直接执行；以源码模型定义为准。')
edit(903,903,'虚构数值不能误认真实验收事实', '**key_insights字段结构**：以下为虚构业务字段示例，市场数字不是实测事实，也不是完整接口响应。实际字段还包含来源进度与索引状态；接口另返回indexing_status、warning。')
edit(733,733,'纠正强制找茬导致合成样本与局限披露被误判', '1. **按任务与证据质检**：不预设报告有问题；区分现实事实、用户提供数据和已声明的合成算例。来源、计算、图表或外推确有错误时仍需指出，不为满足角色而制造缺陷。', '已修正评分流程')
edit(747,757,'审核依据任务范围并避免把诚实局限披露当作偏见', '1. REVIEW_PROMPT：审核当前报告，输出五个1—10分维度和有证据的问题列表；总分由后端按既定权重计算，至少7分且无critical/major问题才通过。\n\n    1. **来源与范围**：用户提供的数据及明确标注的合成样本是限定任务的合法输入；不能据此宣称现实市场事实。\n\n    2. **逻辑与计算**：核对论据、计算、图表与结论是否一致，不忽略真实错误。\n\n    3. **客观性**：样本有限、未外部核验等诚实说明不是偏见；不得强行制造负面评价。\n\n    4. **时效性**：按任务要求判断，正确标注的历史分析或合成数据不因年份较早自动成为错误。\n\n    5. **完整性**：以用户问题和大纲为边界，不强求未要求的外部研究；无真实问题时允许issues为空。', '已修正评分流程')
edit(789,789,'保留严格校验、事实与判定一致性以及针对具体错误的纠正，不缓存未校验审核', '**[质量评分机制]** 模型先核对事实和计算，再列问题，最后提供source_completeness、logical_rigor、objectivity、timeliness、completeness五个1—10分维度；后端严格拒绝布尔值、缺项、非数字、非有限及越界值，按0.3、0.3、0.2、0.1、0.1计算唯一总分，不采用模型自报总分。若事实核查含false/suspicious而issues没有critical/major问题，不能直接判为通过。输出校验失败仅纠正重试一次，反馈错误字段、原值/类型和上次回答，要求按证据重新评估，禁止机械截断、取绝对值、缩放或补分。审核请求绕过缓存。仍失败时保留报告、清除旧评分并提示“审核待确认”；模型分数不等于独立事实核验。', '已修正评分流程')
edit(801,801,'为评分输出稳定性单独配置审核模型，其他Agent配置不变', '**[模型选择]** Critic默认使用qwen-plus，可通过CRITIC_MODEL覆盖；temperature=0、max_tokens=16000，审核请求不读写共享LLM缓存。模型与参数选择不能替代结构和数值校验，评分阈值与权重保持不变。', '已修正评分流程')
path.write_text(json.dumps(sorted(changes, key=lambda row: row['start']), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(f'Prepared {len(changes)} line-addressed changes')
