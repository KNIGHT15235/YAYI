"""Public, explicitly published datasets available through Database Explorer."""
from copy import deepcopy

DEMO_CORPUS_ID = "yayi-optical-cd-2020-2026-demo-v1"
DATASET_NOTICE = ("统计仅描述本次纳入的文献语料，不代表领域年度发文总量。方法标签按题名/摘要关键词多标签匹配，"
                  "不代表主要方法分类或性能排名；来源元数据核验不等同于全文或结论核验。")

TABLE_CATALOG = {
    "research_papers": {
        "label": "科研文献", "description": "正式展示语料的120篇真实文献及可追溯来源",
        "columns": {"paper_id": "文献标识", "title": "文献题名", "publication_year": "发表年份",
                    "authors": "作者", "venue": "期刊/会议", "doi": "DOI", "source_url": "原始来源",
                    "metadata_source": "元数据提供方", "evidence_level": "证据层级", "source_verified": "来源元数据已核验",
                    "corpus_id": "语料集标识", "abstract": "公开摘要", "imported_at": "导入时间"}},
    "research_paper_methods": {
        "label": "文献方法标签", "description": "题名与摘要的关键词多标签结果，可关联科研文献进行统计",
        "columns": {"paper_id": "文献标识", "method_name": "方法标签", "matched_keywords": "命中的关键词",
                    "tagging_rule": "标注规则"}},
    "industry_stats": {
        "label": "行业统计数据", "description": "已导入的行业指标、统计年份与来源",
        "columns": {"id": "ID", "industry_name": "行业名称", "metric_name": "指标名称", "metric_value": "指标值",
                    "unit": "单位", "year": "年份", "quarter": "季度", "month": "月份", "region": "地区",
                    "source": "来源", "source_url": "来源链接", "notes": "说明", "created_at": "创建时间", "updated_at": "更新时间"}},
    "company_data": {
        "label": "企业数据", "description": "已导入的企业经营与财务数据",
        "columns": {"id": "ID", "company_name": "企业名称", "stock_code": "股票代码", "industry": "所属行业",
                    "sub_industry": "细分行业", "revenue": "营收（亿元）", "net_profit": "净利润（亿元）",
                    "gross_margin": "毛利率（%）", "market_cap": "市值（亿元）", "employees": "员工数量",
                    "market_share": "市场份额（%）", "year": "年份", "quarter": "季度", "data_source": "数据来源",
                    "extra_data": "扩展资料", "created_at": "创建时间", "updated_at": "更新时间"}},
    "policy_data": {
        "label": "政策数据", "description": "已导入的政策文件、发布部门与日期",
        "columns": {"id": "ID", "policy_name": "政策名称", "policy_number": "文号", "department": "发布部门",
                    "level": "政策级别", "publish_date": "发布日期", "effective_date": "生效日期", "expiry_date": "失效日期",
                    "category": "分类", "industry": "相关行业", "summary": "摘要", "key_points": "要点",
                    "full_text_url": "原文链接", "impact_level": "影响程度", "affected_entities": "相关主体",
                    "created_at": "创建时间", "updated_at": "更新时间"}},
}
ALLOWED_TABLES = frozenset(TABLE_CATALOG)
QUERY_EXAMPLES = [
    "按发表年份统计科研文献数量，并按年份升序展示折线图",
    "统计每种方法标签对应的文献数量，用柱状图展示",
    "查询2024年至2026年包含Transformer方法标签的论文题名、年份、DOI和原始来源链接",
    "按证据层级统计科研文献数量",
]


def require_table(table_name):
    if table_name not in ALLOWED_TABLES:
        raise ValueError("该数据表未开放给数据库探索")
    return table_name


def catalog_payload(available_tables):
    available = set(available_tables)
    tables = [{"name": name, **deepcopy(info)} for name, info in TABLE_CATALOG.items() if name in available]
    return {"tables": tables, "examples": list(QUERY_EXAMPLES), "notice": DATASET_NOTICE,
            "default_table": "research_papers" if "research_papers" in available else (tables[0]["name"] if tables else ""),
            "corpus": {"id": DEMO_CORPUS_ID, "label": "2020—2026年光学遥感变化检测正式展示语料", "expected_papers": 120}}
