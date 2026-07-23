# -*- coding: utf-8 -*-
"""全市场选股 + 批量分析报告脚本。

在收盘后自动执行两阶段分析：
1. 多策略快速筛选 — 对全市场 A 股并行调用 AlphaSift screen() 执行多个选股策略，
   合并去重后取 Top N，并标注每只股票来源于哪些策略。
2. 完整报告生成 — 对选出的股票逐个执行 StockAnalysisPipeline.run() 生成完整报告。

用法:
  python scripts/screen_then_analyze.py                    # 默认三策略，Top 50
  python scripts/screen_then_analyze.py --top 30           # 取 Top 30
  python scripts/screen_then_analyze.py --strategies dual_low,bull_trend       # 自定义策略
  python scripts/screen_then_analyze.py --no-notify        # 不推送通知
  python scripts/screen_then_analyze.py --debug            # 调试日志
  python scripts/screen_then_analyze.py --dry-run          # 仅筛选不分析
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 环境初始化（与 main.py 保持一致）
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 代理配置
if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("USE_PROXY", "false").lower() == "true":
    proxy_host = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port = os.getenv("PROXY_PORT", "10809")
    proxy_url = f"http://{proxy_host}:{proxy_port}"
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url

from src.config import setup_env, get_config, Config  # noqa: E402
from src.logging_config import setup_logging           # noqa: E402

setup_env()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI 参数解析
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="全市场选股 + 批量分析报告（收盘后任务）",
    )
    parser.add_argument(
        "--strategies",
        type=str,
        default="balanced_alpha,dual_low,shrink_pullback",
        help="选股策略列表，逗号分隔（默认: balanced_alpha,dual_low,shrink_pullback）",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="最终选取的股票数量（默认: 50）",
    )
    parser.add_argument(
        "--market",
        type=str,
        default="cn",
        help="市场代码（默认: cn）",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="不发送推送通知",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅执行筛选，不生成完整报告",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试日志",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _sleep_with_jitter(base_seconds: float, jitter_max: float = 1.0) -> None:
    """带随机抖动的休眠，避免并发请求过于整齐。"""
    time.sleep(min(base_seconds + random.uniform(0, jitter_max), base_seconds * 2))


def exponential_backoff_retry(func, *, max_retries: int = 3, base_delay: float = 5.0) -> Any:
    """指数退避重试装饰器的内联实现。"""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "API 调用失败 (尝试 %d/%d): %s",
                attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                _sleep_with_jitter(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 阶段一：多策略筛选
# ---------------------------------------------------------------------------

def run_screen_phase(
    config: Config,
    strategies: List[str],
    market: str,
    top: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """
    对每个策略执行 screen()，合并去重后取 Top N。

    Returns:
        - stocks: 排序后的股票候选列表，每个元素包含 code, name, score, strategy_sources
        - strategy_map: {strategy_name: [code1, code2, ...]} 标注来源
    """
    from src.services.alphasift_service import AlphaSiftService
    from scripts.alphasift_config_adapter import AlphasiftConfigAdapter

    alphasift = AlphaSiftService(AlphasiftConfigAdapter(config))

    # 存储每个策略的结果: {strategy: [(code, score, candidate_dict), ...]}
    strategy_results: Dict[str, List[Tuple[str, Optional[float], Dict[str, Any]]]] = defaultdict(list)
    # 策略失败记录
    failed_strategies: List[str] = []

    logger.info("=" * 60)
    logger.info("阶段一：多策略快速筛选")
    logger.info("策略列表: %s", ", ".join(strategies))
    logger.info("=" * 60)

    for strategy in strategies:
        logger.info("正在执行策略: %s", strategy)
        try:
            result = exponential_backoff_retry(
                lambda s=strategy: alphasift.screen(strategy=s, market=market, max_results=top * 3),
                max_retries=3,
                base_delay=5.0,
            )

            candidates = result.get("candidates", [])
            if not candidates:
                logger.warning("策略 %s 未返回任何候选股票", strategy)
                continue

            for cand in candidates:
                code = cand.get("code", "")
                score = cand.get("score") or cand.get("llm_score")
                if code:
                    strategy_results[strategy].append((code, score, cand))

            logger.info(
                "策略 %s 完成: 返回 %d 只股票",
                strategy, len(candidates),
            )
            _sleep_with_jitter(2.0)  # 策略间间隔，避免过快请求

        except Exception as exc:
            logger.error("策略 %s 执行失败: %s", strategy, exc)
            failed_strategies.append(strategy)
            # 单个策略失败不阻断其他策略

    if not strategy_results:
        logger.error("所有策略均未返回结果，终止流程")
        return [], {}

    # 打印各策略结果统计
    for strategy, results in strategy_results.items():
        scores = [s for _, s, _ in results if s is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        logger.info(
            "策略 [%s]: %d 只股票, 平均评分 %.2f",
            strategy, len(results), avg_score,
        )

    if failed_strategies:
        logger.warning("以下策略执行失败: %s", ", ".join(failed_strategies))

    # 合并去重：记录每只股票的来源策略和最高分
    stock_info: Dict[str, Dict[str, Any]] = {}
    for strategy, results in strategy_results.items():
        for code, score, cand in results:
            if code not in stock_info:
                stock_info[code] = {
                    "code": code,
                    "name": cand.get("name", ""),
                    "score": score,
                    "llm_score": cand.get("llm_score"),
                    "screen_score": cand.get("screen_score"),
                    "strategy_sources": [strategy],
                    "candidate": cand,
                }
            else:
                info = stock_info[code]
                if strategy not in info["strategy_sources"]:
                    info["strategy_sources"].append(strategy)
                # 更新为最高分
                if score is not None and (info["score"] is None or score > info["score"]):
                    info["score"] = score

    # 按分数排序（有分数的在前，同分按股票代码排序保证确定性）
    ranked_stocks = sorted(
        stock_info.values(),
        key=lambda x: (x["score"] is not None, -(x["score"] or 0), x["code"]),
    )

    # 取 Top N
    selected_stocks = ranked_stocks[:top]

    # 构建策略映射
    strategy_map: Dict[str, List[str]] = defaultdict(list)
    for stock in ranked_stocks:
        for s in stock["strategy_sources"]:
            if stock["code"] not in strategy_map[s]:
                strategy_map[s].append(stock["code"])

    logger.info("")
    logger.info("筛选汇总:")
    logger.info("  参与策略数: %d", len(strategy_results))
    logger.info("  去重后候选: %d 只", len(ranked_stocks))
    logger.info("  最终入选:   %d 只", len(selected_stocks))
    logger.info("")

    return selected_stocks, dict(strategy_map)


# ---------------------------------------------------------------------------
# 阶段二：批量完整分析
# ---------------------------------------------------------------------------

def run_analysis_phase(
    config: Config,
    selected_stocks: List[Dict[str, Any]],
    *,
    send_notification: bool = True,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """
    对选出的股票逐个执行完整 pipeline 分析。

    Returns:
        分析结果列表，每个元素包含 stock_info, analysis_result, success 状态
    """
    from src.core.pipeline import StockAnalysisPipeline

    stock_codes = [s["code"] for s in selected_stocks]

    logger.info("=" * 60)
    logger.info("阶段二：批量完整分析报告")
    logger.info("待分析股票: %d 只", len(stock_codes))
    logger.info("=" * 60)

    pipeline = StockAnalysisPipeline(
        config=config,
    )

    results = []
    total = len(stock_codes)

    for i, stock in enumerate(selected_stocks, 1):
        code = stock["code"]
        name = stock.get("name", "")
        sources = ", ".join(stock.get("strategy_sources", []))
        score = stock.get("score")

        logger.info(
            "[%d/%d] 分析: %s (%s) | 评分: %s | 来源: %s",
            i, total, code, name, score, sources,
        )

        try:
            # 单股分析：调用 pipeline 的单个股票分析能力
            result_data = _analyze_single_stock(
                pipeline, code, dry_run=dry_run, send_notification=send_notification,
            )

            results.append({
                "stock": stock,
                "success": True,
                "result": result_data,
            })

            logger.info("[%d/%d] %s 分析完成", i, total, code)

        except Exception as exc:
            logger.error("[%d/%d] %s 分析失败: %s", i, total, code, exc)
            results.append({
                "stock": stock,
                "success": False,
                "error": str(exc),
                "result": None,
            })

        # 股区间隔，避免触发 API 限流
        if i < total:
            _sleep_with_jitter(3.0)

    return results


def _analyze_single_stock(
    pipeline: "StockAnalysisPipeline",
    stock_code: str,
    *,
    dry_run: bool = False,
    send_notification: bool = True,
) -> Dict[str, Any]:
    """
    对单只股票运行完整分析流程。

    通过构造仅含一只股票的 pipeline 调用来实现，复用已有的技术分析、
    LLM 分析、新闻检索等全部能力。
    """
    # 直接调用 pipeline.run 但只传入当前股票
    results = pipeline.run(
        stock_codes=[stock_code],
        dry_run=dry_run,
        send_notification=send_notification,
    )

    if results:
        # 返回第一只股票的分析结果
        return {
            "analysis": results[0].to_dict() if hasattr(results[0], "to_dict") else str(results[0]),
        }
    return {}


# ---------------------------------------------------------------------------
# 总结输出
# ---------------------------------------------------------------------------

def print_summary(
    selected_stocks: List[Dict[str, Any]],
    analysis_results: List[Dict[str, Any]],
    strategy_map: Dict[str, List[str]],
    strategies: List[str],
    dry_run: bool,
) -> None:
    """输出最终总结摘要。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("任务完成总结")
    logger.info("=" * 60)

    # --- 筛选统计 ---
    logger.info("")
    logger.info("--- 筛选统计 ---")
    logger.info("执行策略: %s", ", ".join(strategies))
    logger.info("各策略命中股票数:")
    for strategy, codes in strategy_map.items():
        logger.info("  %s: %d 只", strategy, len(codes))

    # --- 多策略重合 ---
    multi_strategy = [s for s in selected_stocks if len(s.get("strategy_sources", [])) > 1]
    if multi_strategy:
        logger.info("")
        logger.info("--- 多策略重合标的 (重点关注) ---")
        for stock in sorted(multi_strategy, key=lambda x: -len(x.get("strategy_sources", []))):
            sources = ", ".join(stock.get("strategy_sources", []))
            logger.info(
                "  %s (%s) | 评分: %s | 策略: %s",
                stock["code"], stock.get("name", ""), stock.get("score"), sources,
            )

    # --- 分析统计 ---
    if dry_run:
        logger.info("")
        logger.info("--- 干跑模式 ---")
        logger.info("已执行筛选，跳过完整分析阶段")
        return

    total = len(analysis_results)
    success_count = sum(1 for r in analysis_results if r.get("success"))
    fail_count = total - success_count

    logger.info("")
    logger.info("--- 分析统计 ---")
    logger.info("入选股票: %d 只", total)
    logger.info("分析成功: %d 只", success_count)
    logger.info("分析失败: %d 只", fail_count)

    if fail_count > 0:
        failed_codes = [r["stock"]["code"] for r in analysis_results if not r.get("success")]
        logger.info("失败股票: %s", ", ".join(failed_codes))

    # --- 高分标的 TOP 10 ---
    scored = [
        r for r in analysis_results
        if r.get("success") and r.get("stock", {}).get("score") is not None
    ]
    if scored:
        top_10 = sorted(scored, key=lambda x: -(x["stock"]["score"] or 0))[:10]
        logger.info("")
        logger.info("--- 综合评分 TOP 10 ---")
        for rank, r in enumerate(top_10, 1):
            stock = r["stock"]
            logger.info(
                "  %d. %s (%s) | 评分: %.2f | 策略: %s",
                rank, stock["code"], stock.get("name", ""),
                stock["score"], ", ".join(stock.get("strategy_sources", [])),
            )

    # --- 时间戳 ---
    logger.info("")
    logger.info("任务完成时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    # 解析策略列表
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    if not strategies:
        logger.error("未指定任何策略")
        return 1

    # 设置日志级别
    setup_logging(debug=args.debug)

    logger.info("=" * 60)
    logger.info("全市场选股 + 批量分析报告")
    logger.info("开始时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    # 加载配置
    config = get_config()

    # --- 阶段一：多策略筛选 ---
    try:
        selected_stocks, strategy_map = run_screen_phase(
            config=config,
            strategies=strategies,
            market=args.market,
            top=args.top,
        )
    except Exception as exc:
        logger.error("阶段一筛选失败: %s", exc, exc_info=True)
        return 1

    if not selected_stocks:
        logger.warning("未筛选到任何股票，终止流程")
        return 0

    # 保存筛选结果到 JSON 文件
    screen_output_path = _PROJECT_ROOT / "data" / "screen_results.json"
    screen_output_path.parent.mkdir(parents=True, exist_ok=True)
    screen_payload = {
        "timestamp": datetime.now().isoformat(),
        "strategies": strategies,
        "top": args.top,
        "stocks": selected_stocks,
        "strategy_map": strategy_map,
    }
    with open(screen_output_path, "w", encoding="utf-8") as f:
        json.dump(screen_payload, f, ensure_ascii=False, indent=2, default=str)
    logger.info("筛选结果已保存至: %s", screen_output_path)

    # --- 阶段二：批量分析（可选） ---
    if args.dry_run:
        logger.info("干跑模式：跳过完整分析阶段")
        print_summary(selected_stocks, [], strategy_map, strategies, dry_run=True)
        return 0

    try:
        analysis_results = run_analysis_phase(
            config=config,
            selected_stocks=selected_stocks,
            send_notification=not args.no_notify,
            dry_run=False,
        )
    except Exception as exc:
        logger.error("阶段二分析失败: %s", exc, exc_info=True)
        # 即使分析阶段失败，仍然输出总结
        analysis_results = []

    # --- 输出总结 ---
    print_summary(selected_stocks, analysis_results, strategy_map, strategies, dry_run=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
