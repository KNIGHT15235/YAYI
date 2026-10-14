"""Apply reviewed, line-addressed edits to a preserved copy; never alter Downloads."""
import hashlib
import json
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
source = AUDIT / '雅意-原始文档.md'
raw = source.read_bytes()
lines = raw.decode('utf-8-sig').splitlines()
changes = sorted(json.loads((AUDIT / 'alignment_doc_changes.json').read_text(encoding='utf-8')), key=lambda row: row['start'])
cursor = 0
aligned = []
details = [
    '# 雅意.md 文档逐项修改清单', '',
    '所有行号均对应未修改的943行原文，不是修改后文档。原文定位副本：`雅意-原始文档.md`。',
    f'原始文件SHA-256：`{hashlib.sha256(raw).hexdigest()}`。', '',
    '以下每项给出原文位置、修改原因和可直接替换的完整文字。未列出的段落保留；新版本为`雅意-代码对齐版.md`。', '',
    '|编号|原文行号|章节|处理类别|原因|', '|---|---|---|---|---|',
]
for index, change in enumerate(changes, 1):
    start, end = change['start'], change['end']
    if not (cursor < start <= end <= len(lines)):
        raise ValueError(f'Overlapping or out of range edit: {start}..{end}')
    heading = next((line for line in reversed(lines[:start]) if line.startswith('#')), '# 雅意')
    category = change.get('category', '按实际代码改写')
    change['id'] = f'D{index:02}'
    change['heading'] = heading.lstrip('# ').replace('|', '／')
    details.append(f'|{change["id"]}|{start}—{end}|{change["heading"]}|{category}|{change["reason"].replace("|", "／")}|')
    aligned.extend(lines[cursor:start - 1])
    aligned.extend(change['replacement'].splitlines())
    cursor = end
aligned.extend(lines[cursor:])
for change in changes:
    details.extend(['', f'## {change["id"]}：原文第{change["start"]}—{change["end"]}行', '',
                    f'章节：{change["heading"]}', '', '原文起始：', '',
                    '> ' + lines[change['start'] - 1], '', '修改原因：' + change['reason'], '',
                    '将上述行范围整体替换为：', '', '````markdown', change['replacement'], '````'])
appendix_path = AUDIT / 'alignment_document_appendix.md'
if appendix_path.exists():
    appendix = appendix_path.read_text(encoding='utf-8')
    aligned.extend(['', appendix])
    details.extend(['', '## 文末新增内容', '', '在原文第943行后新增以下运行与限制说明：', '',
                    '````markdown', appendix, '````'])
(AUDIT / '雅意-代码对齐版.md').write_text('\n'.join(aligned) + '\n', encoding='utf-8')
(AUDIT / '文档逐项修改清单.md').write_text('\n'.join(details) + '\n', encoding='utf-8')
print(f'{len(changes)} non-overlapping edits; original preserved; {len(aligned)} aligned lines')
