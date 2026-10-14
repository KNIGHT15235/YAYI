"""Two bounded live qwen-plus Critic samples; no mocks, DB, cache, or old evidence writes."""
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


async def run_sample(name, growth):
    config = get_config()
    critic = CriticMaster(config.api_key, config.base_url, "qwen-plus")
    critic.client = critic.client.with_options(timeout=55, max_retries=0)
    responses = []
    original_call = critic.call_llm

    async def capture(*args, **kwargs):
        response = await original_call(*args, **kwargs)
        responses.append(response)
        return response

    critic.call_llm = capture
    state = create_initial_state(
        "请仅根据用户给定的合成企业收入样本，说明三年的收入变化，明确数据来源与适用范围；不检索外部信息。",
        "audit-qwen-critic-" + name, search_web=False, search_local=False)
    report = f"""# 合成企业收入变化
本报告为软件演示，全部数据由用户提供，不代表真实公司或市场。
| 年份 | 收入（测试单位） |
|---|---:|
| 2023 | 10 |
| 2024 | 20 |
| 2025 | 30 |

2024年相较2023年收入增长{growth}%，2025年相较2024年收入增长50%。
同比增长率的计算公式为（当年收入－上年收入）÷上年收入×100%。
每年的绝对增量均为10个测试单位，两年合计增加20个测试单位。
来源：用户在本次任务提供的三条合成测试数据，未外部核验。
结论仅适用于给定样本，不推断真实市场趋势、增长原因或未来业绩。"""
    state.update(phase="reviewing", final_report=report, iteration=1, max_iterations=1)
    state["outline"] = [{"id": "income", "title": "合成企业收入变化", "status": "drafted"}]
    state["facts"] = [{"id": "input_income", "content": "用户提供的合成样本：2023年收入10、2024年收入20、2025年收入30测试单位，仅用于软件演示。",
                       "source_name": "本次用户提供的合成测试输入", "source_url": "", "credibility_score": 1.0}]
    state["data_points"] = [{"id": f"data_{year}", "name": f"{year}年合成收入", "value": amount,
                              "unit": "测试单位", "year": year, "source": "本次用户提供的合成测试输入"}
                             for year, amount in [(2023, 10), (2024, 20), (2025, 30)]]
    started = time.monotonic()
    error = None
    try:
        await asyncio.wait_for(critic.process(state), timeout=125)
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    finally:
        critic.client.close()
    dimensions = state.get("quality_dimensions", {})
    try:
        computed = critic._weighted_score(dimensions)
        valid = state.get("quality_review_status") == "confirmed" and state.get("quality_score") == computed
    except (ValueError, TypeError, OverflowError):
        valid = False
    reviews = [item["content"] for item in state["messages"] if item["type"] == "review"]
    verdict = reviews[-1].get("verdict") if reviews else None
    issues = state.get("critic_feedback", [])
    calculation_issues = []
    for issue in issues:
        detail = " ".join(str(issue.get(key, "")) for key in ("description", "evidence", "suggestion"))
        if ("20%" in detail or "20％" in detail) and ("100%" in detail or "100％" in detail):
            calculation_issues.append(issue)
    result = {
        "sample": name, "model": "qwen-plus", "elapsed_seconds": round(time.monotonic() - started, 2),
        "response_count": len(responses), "valid_five_dimensions_and_weighted_score": valid,
        "quality_review_status": state.get("quality_review_status"), "quality_score": state.get("quality_score"),
        "quality_dimensions": dimensions, "verdict": verdict, "phase": state["phase"],
        "report_preserved": state["final_report"] == report,
        "calculation_error_identified": bool(calculation_issues), "calculation_issues": calculation_issues,
        "error": error, "review_events": reviews, "issues": issues, "report": report,
        "raw_model_responses": responses,
    }
    result["passed"] = bool(valid and result["report_preserved"] and state["phase"] == "completed" and error is None
                            and (name != "incorrect_growth" or (calculation_issues and verdict == "needs_revision")))
    print(json.dumps({k: v for k, v in result.items() if k not in {
        "review_events", "issues", "calculation_issues", "report", "raw_model_responses"}}, ensure_ascii=False), flush=True)
    return result


async def main():
    results = await asyncio.gather(run_sample("correct_growth", 100), run_sample("incorrect_growth", 20))
    output = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Standalone real Critic using existing account/endpoint and explicit qwen-plus; no full research, no search/DB/cache writes. Prior evidence untouched.",
              "passed": all(result["passed"] for result in results), "results": results}
    (ROOT / "audit" / "critic-qwen-results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output["passed"]


if __name__ == "__main__":
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(0 if asyncio.run(main()) else 1)
