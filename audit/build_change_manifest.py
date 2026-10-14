"""Create a bounded source-change inventory without reading secret configuration."""
import difflib
import hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
backup_roots = [root / 'audit' / 'alignment-before', root / 'audit' / 'scoring-before']
before_files = {}
for backup_root in backup_roots:
    for before in sorted(backup_root.rglob('*')):
        if before.is_file():
            before_files.setdefault(before.relative_to(backup_root), before)
rows = []
for relative, before in sorted(before_files.items()):
    if relative.parts[0] not in {'backend', 'frontend'} and relative.as_posix() != 'README.md':
        continue
    if before.suffix not in {'.py', '.tsx', '.ts', '.scss', '.json', '.md', '.txt'}:
        continue
    after = root / relative
    if not after.exists() or before.read_bytes() == after.read_bytes():
        continue
    a = before.read_text(encoding='utf-8-sig').splitlines()
    b = after.read_text(encoding='utf-8-sig').splitlines()
    additions = deletions = 0
    for tag, i, j, k, l in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag in ('replace', 'delete'):
            deletions += j - i
        if tag in ('replace', 'insert'):
            additions += l - k
    rows.append((relative.as_posix(), '修改', f'+{additions} / -{deletions}'))

new_paths = [
    'backend/app/service/knowledge_access.py',
    'backend/app/service/response_cache.py',
    'backend/app/service/memory_jobs.py',
    'backend/app/service/research_access.py',
    'backend/app/service/research_guard.py',
    'backend/app/service/deep_research_v2/safe_fetch.py',
    'frontend/src/pages/database/query-visualization.tsx',
    'frontend/src/pages/knowledge/search.tsx',
]
known = {row[0] for row in rows}
for relative in new_paths:
    target = root / relative
    if not target.is_file():
        raise ValueError(f'Missing source file: {relative}')
    if relative not in known:
        rows.append((relative, '新增', f'+{len(target.read_text(encoding="utf-8").splitlines())}'))
if 'backend/requirements.txt' not in known:
    rows.append(('backend/requirements.txt', '修改', '新增Pillow>=10.0.0声明；当前环境已安装'))

lines = ['# 本轮代码修改清单', '',
         '范围：功能补齐及评分修复轮次；优先对比`audit/alignment-before`备份，仅在缺少该基线时使用`audit/scoring-before`。行数为文本差异统计，不代表功能数量。测试脚本、结果日志和文档生成材料另存于audit目录，不逐项列入运行源码清单。', '',
         '|文件|类型|文本变更|', '|---|---|---|']
for relative, kind, counts in sorted(rows):
    lines.append(f'|[{relative}](../{relative})|{kind}|{counts}|')
lines += ['', f'共列出{len(rows)}个运行/构建/启动说明文件。没有修改云端计费设置或覆盖`.env`。', '',
          '对应行为与测试见[功能补齐实施报告](功能补齐实施报告.md)。']
(root / 'audit' / '代码修改清单.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
print(f'{len(rows)} source/config documentation files inventoried')
