# Spec: 全市场选股 + 批量分析报告 (screen-then-analyze)

## Objective

提供一个 CLI 脚本，在收盘后自动执行两阶段分析：

1. **阶段一：多策略快速筛选** — 对全市场 A 股并行调用 AlphaSift `screen()` 执行多个选股策略，合并去重后取 Top 50，并标注每只股票来源于哪些策略。
2. **阶段二：完整报告生成** — 对这 50 只股票逐个执行 `StockAnalysisPipeline.run()` 生成完整的个股分析报告（技术分析 + LLM 深度分析 + 新闻检索 + 推送通知）。
3. **总结输出** — 最后输出一份汇总摘要，方便用户快速关注重点。

**关键约束**：不修改任何现有代码文件；所有新增逻辑放在独立脚本中。

## Commands

```bash
# 基本用法：默认 bull_trend,ma_golden_cross,volume_breakout 三个策略，Top 50
python scripts/screen_then_analyze.py

# 自定义策略列表
python scripts/screen_then_analyze.py --strategies bull_trend,ma_golden_cross,volume_breakout,shrink_pullback,hot_theme

# 自定义返回数量
python scripts/screen_then_analyze.py --top 30

# 跳过通知推送（仅生成报告文件）
python scripts/screen_then_analyze.py --no-notify

# 调试模式（详细日志）
python scripts/screen_then_analyze.py --debug
```

## Tech Stack

- Python 3.10+（与项目一致）
- 依赖：直接 import 项目已有模块（`src.services.alphasift_service.AlphaSiftService`、`src.core.pipeline.StockAnalysisPipeline`、`src.config.get_config`），不引入新依赖

## Project Structure

```
scripts/
└── screen_then_analyze.py    # 新增脚本（唯一改动文件）
```

**不修改任何现有文件**。脚本通过 import 项目内部模块编排流程。

## Code Style

- 文件头注释说明用途和使用方式
- 使用项目已有的 `logging` 配置（通过 `setup_logging`）
- 函数/类命名使用 snake_case / CamelCase，与项目风格一致
- 错误处理：API 失败时退避重试（指数退避，最多 3 次），单个策略失败不阻断其他策略
- 进度输出：每个阶段打印清晰的进度信息

示例：

```python
# -*- coding: utf-8 -*-
"""全市场选股 + 批量分析报告脚本。

用法:
  python scripts/screen_then_analyze.py                    # 默认三策略，Top 50
  python scripts/screen_then_analyze.py --top 30           # 取 Top 30
  python scripts/screen_then_analyze.py --no-notify        # 不推送通知
"""
from __future__ import annotations

import logging
import time
import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import dotenv_values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="全市场选股 + 批量分析报告（收盘后任务）",
    )
    parser.add_argument(
        "--strategies",
        type=str,
        default="bull_trend,ma_golden_cross,volume_breakout",
        help="选股策略列表，逗号分隔（默认: bull_trend,ma_golden_cross,volume_breakout）",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="最终选取的股票数量（默认: 50）",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="不发送推送通知",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试日志",
    )
    return parser.parse_args()


logger = logging.getLogger(__name__)


def main() -> int:
    args = parse_args()
    # ... 实现
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## Testing Strategy

- 本脚本为端到端编排脚本，不写单元测试（依赖 AlphaSift Service 和 Pipeline 已有的测试覆盖）
- 手动验证：
  1. `--dry-run` 模式（仅筛选不分析）验证多策略合并去重逻辑
  2. 完整运行一只股票验证 pipeline 集成
  3. 验证 API 超时/报错时的退避重试行为

## Boundaries

### Always do
- 不修改 `main.py`、`pipeline.py`、`alphasift_service.py`、`config.py` 等任何现有文件
- 不引入新的 pip 依赖
- 单个策略 screen 失败时记录日志并继续其他策略
- 单个股票分析失败时记录日志并继续下一只
- API 报错时指数退避重试（初始 5s，最多 3 次）
- 输出清晰的进度日志和最终总结

### Ask first
- 修改 `.env.example` 添加新配置项（如需）
- 修改 `AGENTS.md` 或 `docs/` 中的文档

### Never do
- 修改现有模块的公开接口或行为
- 提交代码、打 tag、push
- 硬编码 API key 或路径

## Success Criteria

1. 脚本可独立运行：`python scripts/screen_then_analyze.py`
2. 支持多策略并行筛选，结果合并去重并标注来源策略
3. Top N 股票全部跑完完整 pipeline 分析
4. 单个 API 调用失败时自动退避重试（最多 3 次）
5. 最终输出一份文字总结（含筛选统计、分析统计、重点关注标的）
6. 不修改任何现有代码文件

## Open Questions

无。以上假设已确认。
