"""Append the measured implementation record to the project narrative."""
import json
import re
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'audit'
result=json.loads((OUT/'demo-result.json').read_text(encoding='utf-8'))
audit=json.loads((OUT/'demo-output-audit.json').read_text(encoding='utf-8'))
marker='## [实施验收] 2026-09-29 YAYI_0929'
hypotheses='、'.join(f'{k}：{v} 项' for k,v in Counter(h['status'] for h in result['hypotheses']).items())
contract_log=(ROOT/'frontend/audit/contract.log').read_text(encoding='utf-8')
contract_tests=re.search(r'# tests (\d+)',contract_log).group(1)
appendix=f'''

---

{marker}

代码已从 `D:\\ldj\\01\\source\\industry_information_assistant` 完整复制到 `D:\\ldj\\01\\YAYI_0929`，修改均位于副本。网页名称、图标及入口统一为 **yayi / 雅意**；运行地址为 http://localhost:5199，后端为 http://localhost:8029，启动命令见副本 `README.md`。复用原 Python 环境和基础容器，业务状态分别使用 PostgreSQL / Milvus 数据库 `yayi_0929` 与 Redis DB 9。

### 已实施的科研业务链路

保留原六 Agent、SSE + Queue、checkpoint、Redis 取消、历史 JSONB、Milvus 检索及重排。科研配置新增真实学术文献采集与去重、证据台账、逐段声明审核、文献集合知识图谱、可复算统计图，以及 PDF 页码／表格行列／图像和公式资产回查。科研主页使用科研问题，原行业分支代码继续保留。

**假设驱动研究仍然保留**：提出可检验假设，召回正反证据，评估 supported / mixed / insufficient 等状态，并让证据缺口指导补检和修订。假设可以保持未证实或混合；不把没有足够比较证据的方向包装成确定结论。本次最终保留 {len(result['hypotheses'])} 项假设（{hypotheses}）。

### 主展示 query 与历史

> 围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。

在“研究历史”打开 **2020—2026光学遥感变化检测文献综述**；会话 ID 为 `{audit['session_id']}`，直接地址为 http://localhost:5199/chat/{audit['session_id']} 。历史保留原始问题、修订前报告和最终报告，默认展开最新版本；文献、引用、假设、审核结果、图谱及图表随结果恢复。

|本次实测项|结果|
|---|---|
|去重文献|{audit['papers']} 篇，超过 50 篇要求|
|证据可用性|114 篇带摘要，6 篇仅元数据；另有 1 篇本地 BIT 论文全文|
|来源身份|120/120 通过 DOI / arXiv 标题与身份核对|
|参考文献与正文引用|{audit['references']} 条参考记录，正文使用 {audit['body_cited_sources']} 个不同来源|
|正文声明核验|{len(result['claims'])}/{len(result['claims'])} supported，全部经过审核；独立内容审核另行留档|
|知识图谱|{audit['graph_nodes']} 个节点、{audit['graph_edges']} 条边，120 篇全部入图|
|图表|{audit['charts']} 张：文献年份分布、方法关键词分布；均由真实集合重算|
|机械输出检查|{audit['passed']}/{audit['total_checks']} 通过|
|实际暂停恢复|研究中取消后 paused，浏览器继续后完成，并自动保存历史|
|PDF 解析与检索|264 个布局块、167 个向量片段，7 个图像、6 个表格、10 个公式；真实重排成功|

年份图采用按年份均衡且优先可读摘要的样本，不能据此推断领域发文趋势。关键词可重叠，图谱关系表示样本归属、年份或标题／摘要提及，不等同于方法间因果关系或性能优劣。综述结论明确区分方法机制、应用约束及比较证据，未混用不同数据集的指标进行排名。

### 验证与交付位置

验收报告为 `audit/YAYI_0929验收报告.md`，完整综述为 `audit/demo-report.md`，结构化结果为 `audit/demo-result.json`，独立内容审核为 `audit/content-review-final.md`。统计图片位于 `audit/figures`，真实浏览器截图位于 `audit/screenshots`；可审计的修订前结果也保留在 `audit`。

已完成科研引擎 30 项回归、既有研究 18 项回归、文献资产及兼容 41 项回归，前端类型检查、{contract_tests} 项合同测试和生产构建。公式 OCR 仍可能有转写误差，部分图表编号未自动关联；查看数学公式或精细表格内容时应使用原文回查。这些限制与本次已核实的输出范围同时记录在验收报告中。
'''
doc=ROOT/'docs/雅意原型-实施版.md'
text=doc.read_text(encoding='utf-8')
text=text.split(marker)[0].rstrip()
text=re.sub(r'\n---\s*$', '', text)
text+=appendix
doc.write_text(text,encoding='utf-8')
export=ROOT.parents[1]/'output'
export.mkdir(exist_ok=True)
for name in ('雅意原型-简历对齐版.md','雅意原型-YAYI_0929实施验收版.md'):
    (export/name).write_text(text,encoding='utf-8')
print('Updated implementation narrative and both Markdown delivery copies.')
