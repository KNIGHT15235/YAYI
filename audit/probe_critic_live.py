"""Bounded live Critic probe using only synthetic input; no database/cache/user writes."""
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env")
sys.path.insert(0, str(ROOT / "backend" / "app"))

from config.llm_config import get_config
from service.deep_research_v2.agents.critic import CriticMaster
from service.deep_research_v2.state import create_initial_state


async def main():
    config = get_config()
    critic = CriticMaster(config.api_key, config.base_url, config.agents.critic.model)
    critic.client = critic.client.with_options(timeout=60, max_retries=0)
    responses = []
    call_llm = critic.call_llm

    async def capture(*args, **kwargs):
        response = await call_llm(*args, **kwargs)
        responses.append(response)
        return response

    critic.call_llm = capture
    state = create_initial_state(
        "软件测试：审核以下合成企业收入趋势说明。数据为用户提供的演示样本，不代表真实公司或市场；不要检索外部信息。",
        "audit-critic-only", search_web=False, search_local=False)
    report = """# 合成企业收入趋势（软件测试）

本报告仅分析用户输入的演示样本，不代表真实公司经营状况或市场调查。

| 年份 | 收入（测试单位） |
|---|---:|
| 2023 | 10 |
| 2024 | 20 |
| 2025 | 30 |

2024 年相较 2023 年增长 100%，2025 年相较 2024 年增长 50%；两年间收入增加 20 个测试单位。
计算口径为（当年值－上年值）÷上年值。这说明样本中的绝对年度增量都是 10，但同比增速下降。

来源：本次用户提供的三条合成数据。没有外部核验，也不能推断增长原因、真实市场规模或未来业绩。
数据年份止于 2025 年；样本有限，仅用于验证系统计算与报告功能。"""
    state.update(phase="reviewing", final_report=report, iteration=1, max_iterations=1)
    state["outline"] = [{"id": "section_a", "title": "合成收入趋势", "status": "drafted"}]
    state["facts"] = [{"id": "fact_a", "content": "用户提供的合成样本：2023 年收入 10、2024 年 20、2025 年 30 测试单位，仅用于软件测试。",
                       "source_name": "本次用户提供的合成数据", "credibility_score": 1.0}]
    state["data_points"] = [{"id": f"dp_{year}", "name": f"{year}年合成收入", "value": value,
                              "unit": "测试单位", "year": year, "source": "本次用户提供的合成数据"}
                             for year, value in [(2023, 10), (2024, 20), (2025, 30)]]
    started = time.monotonic()
    error = None
    try:
        await asyncio.wait_for(critic.process(state), timeout=135)
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    dimensions = state.get("quality_dimensions", {})
    try:
        computed = critic._weighted_score(dimensions)
        valid = state.get("quality_review_status") == "confirmed" and state.get("quality_score") == computed
    except ValueError:
        valid = False
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": config.agents.critic.model,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "response_count": len(responses),
        "valid_five_dimensions_and_weighted_score": valid,
        "report_preserved": state["final_report"] == report,
        "phase": state["phase"],
        "quality_review_status": state.get("quality_review_status"),
        "quality_score": state.get("quality_score"),
        "quality_dimensions": dimensions,
        "review_events": [message["content"] for message in state["messages"] if message["type"] == "review"],
        "error": error,
        "raw_model_responses": responses,
        "scope": "Standalone Critic with synthetic input, no full research, no search, no database writes; prior 9/11 integration evidence unchanged."
    }
    (ROOT / "audit" / "critic-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"raw_model_responses", "review_events"}}, ensure_ascii=False), flush=True)
    return valid and state["final_report"] == report and state["phase"] == "completed"


if __name__ == "__main__":
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(0 if asyncio.run(main()) else 1)
