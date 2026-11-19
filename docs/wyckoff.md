# Wyckoff 信号引擎

> 状态：开发中（`feat/wyckoff-screening-drawdown` 分支）。领域层、数据层、服务层、只读 API、告警桥接与前端最小页面已落地；接口与告警默认关闭。

## 1. 定位

本项目中的 Wyckoff「信号识别」本身就是一种**选股策略**：基于"强势突破（SOS）→ 缩量回踩（LPS）"的威科夫形态，按交易日扫描全市场，筛出符合形态的候选标的。用于：

1. 按交易日扫描全市场，产出候选标的与客观特征，而非买卖建议；
2. 对单只标的给出触发点与 K 线上下文，供人工复核。

与 `src/services/screening/` 的关系：本模块是一套**独立实现**的选股策略，不复用 screening 的多因子评分框架——输出是客观触发点与形态特征，而非打分排序。此外**不做** LLM 分析（交给主流程）、不建独立数据库（复用 `stock_daily`）。

## 2. 分层与落点

| 层 | 落点 | 职责 | I/O |
| --- | --- | --- | --- |
| 事实层 | `src/services/wyckoff/signals.py` | SOS → LPS 触发点识别 | 无 |
| 特征层 | `src/services/wyckoff/features.py` | Spring / Test / 量价趋势 | 无 |
| 数据层 | `src/services/wyckoff/data.py` | 从 `StockRepository` 读日线并转为 `DailyBar` | 只读数据库 |
| 服务层 | `src/services/wyckoff/service.py` | 编排扫描、缓存、陈旧判定 | 只读 |
| API | `api/v1/endpoints/wyckoff.py` + `api/v1/schemas/wyckoff.py` | 只读查询接口 | — |
| 前端 | `apps/dsa-web/src/pages/WyckoffPage.tsx` + `apps/dsa-web/src/components/wyckoff/WyckoffChart.tsx` | 信号列表 + 个股 K 线详情 | 调用只读 API |

领域层（`models` / `signals` / `features`）不得引入数据库、网络或配置读取，以便用纯单测覆盖。

## 3. 数据契约

`DailyBar` 承载完整 OHLCV 加两个指标：

- `ma20`：收盘价 20 日简单均线（`min_periods=1`）；
- `volume_ratio`：当日成交量 / 前 5 个交易日平均成交量。

两者均由 `data_provider` 在抓取入库时计算并写入 `stock_daily`。本模块**不重算**这两个指标，避免同一指标出现第二套口径。

缺失值一律保留为 `None`，不替换为 `0`。任何"缺失 vs 形态不存在"的区分都通过特征的 `reason` 字段显式表达（如 `missing_data`、`no_breakdown`、`new_low`、`no_down_day`）。

### 3.1 窗口策略

调用方必须传入**可用完整历史**。触发点识别本身不做内部截断：截断历史会改变突破窗口的判定基准，导致同一天的信号随查询区间漂移。

`WyckoffDataProvider.load_series()` 默认加载全量历史；需要限定区间时必须显式传 `start_date` / `end_date`。

### 3.2 指标回填

历史库中若 `ma20` / `volume_ratio` 为空或非有限值，特征层会显式降级为 `missing_data`，不会用 `0` 伪造缩量日。存量数据用 `scripts/backfill_daily_indicators.py` 一次性补齐：

- 复用 `BaseFetcher._calculate_indicators`，与抓取入库完全同口径，不引入第二套公式；
- 只补 `NULL` 或非法值，已有合法值跳过，可重复执行；
- 默认 dry-run，先打印「检查股票数 / 待回填股票数 / 待回填行数 / 无法计算行数」，确认后加 `--apply` 才写库；另支持 `--codes` / `--max-codes` 限定范围。

实测：当前仓库库 `stock_daily` 5879 行，`ma20` / `volume_ratio` NULL 均为 0，脚本判定待回填 0 行，无需变更数据。

## 4. 配置与只读 API

### 4.1 配置开关

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WYCKOFF_ENABLED` | `false` | 总开关。关闭时 `/api/v1/wyckoff/*` 统一返回 403（`detail.error = wyckoff_disabled`）。 |

配置项已在 `src/core/config_registry.py` 注册（Web 设置页可改），帮助文案见 `apps/dsa-web/src/locales/settingsHelp.ts`，示例见 `.env.example`。

### 4.2 接口契约

两个接口都只读本地 `stock_daily`，不触发抓取、不写库，响应字段以 `api/v1/schemas/wyckoff.py` 为准。

`GET /api/v1/wyckoff/signals`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `date` | `YYYY-MM-DD` | 本地最新交易日 | 目标信号日 |
| `codes` | 逗号分隔字符串 | 全部股票 | 限定扫描范围 |
| `limit` | 1..5000 | 不限 | 最多扫描股票数 |

响应含 `date` / `latest_data_date` / `is_stale` / `total` / `codes_scanned` / `codes_without_data` / `signals[]`。`is_stale` 表示本地日线落后于最近一个工作日（仅跳过周末，不建模节假日）。`signals[]` 中 `sos_date` 为突破日、`trigger_date` 为缩量回踩（入场）日。

`GET /api/v1/wyckoff/detail/{code}`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `bars` | 20..1000 | 250 | 返回的末段日线根数 |

返回升序日线与窗口内触发点；该股票无日线时返回 404（`wyckoff_no_data`）。

## 5. 决策记录

### D1 历史数据：重算，不做旧库导入

旧实现的历史信号存放在 `filter_and_analysis/data/wyckoff_backtest.db`（独立 SQLite）。新实现不导入该库，也不保留其表结构。

理由：旧库的三条信号产出路径（`backtest_result`、`daily_signal`、实时扫描）口径互不一致，导入只会把不一致固化进新系统。以上游 `stock_daily` 为唯一事实来源重算，结果可复现、可校验。

### D2 K 线图：使用 `echarts` 核心包 + 自建 React 封装

结论：引入 `echarts`（按需引入 `CandlestickChart` / `LineChart` / `BarChart` / `DataZoomComponent` / `TooltipComponent` / `GridComponent`），不使用 `echarts-for-react`，由页面侧用一个 `useEffect` + `ref` 的小封装管理 `init` / `resize` / `dispose`。

理由：

1. **能力匹配**：K 线需要蜡烛图 + 成交量副图 + 十字光标 + 缩放平移。`recharts`（当前唯一图表依赖）没有蜡烛图基础组件，只能用自定义 shape 拼，缩放平移还得自己实现。
2. **依赖体积可控**：只加 `echarts` 一个包，按需引入后只打进 Wyckoff 页面 chunk（路由级 `lazy`），不影响首屏。相比旧实现同时引入 `echarts` + `echarts-for-react` 少一个包。
3. **维护成本**：手绘 SVG 需要自己实现坐标轴、tooltip、缩放、十字线，维护成本远高于引入成熟图表库；`echarts-for-react` 这层包装在 React 19 下收益有限，还多一处版本兼容面。
4. **一致性**：`recharts` 继续用于其余统计类图表；K 线是唯一的金融时序图，独立选型不破坏现有栈。

未采纳方案：

- 仅用 `recharts` 自定义 shape：缩放/十字光标缺失，交互不达标；
- 自绘 SVG：零依赖但维护成本过高，且无障碍与高频重绘表现差。

### D3 "最新信号"口径：完整历史重算 + 缓存

结论：每个标的都用完整历史重算，不采用增量窗口扫描；结果按 `(code, 末根 K 线日期, K 线根数, 配置指纹)` 缓存，末根 K 线变化或配置变化即失效。

理由：增量扫描用固定回看窗口（旧实现为 60 日）会让边界处的 SOS/LPS 被截断，同一天信号随查询窗口变化而漂移。确定性优先，接受的代价是首次全市场扫描较慢，由缓存摊薄后续成本。

### D4 价格告警：复用上游 alert 路由，不新建通知链路

结论：Wyckoff 告警只负责把信号转成 `price_cross` 告警规则（`source="wyckoff"`，落 `AlertService`），投递完全交给上游 `AlertWorker` → `NotificationService.send_with_results(..., route_type="alert")`。

理由：

1. 上游已有完整的规则持久化、轮询、冷却、触发审计（`alert_trigger` / `alert_notification`）与通知路由，另建链路会重复实现这些能力。
2. `notify` 层的渠道矩阵（wechat / dingtalk / feishu / telegram / email / pushover / ntfy / gotify / pushplus / serverchan3 / custom / discord / slack / astrbot）与路由开关 `NOTIFICATION_ALERT_CHANNELS` 已可直接复用，邮件是其中一条。
3. 旧实现的失败正好是"桥接自己发通知"以外的部分都做对了：只建规则、失败不阻断主流程、同股同向同价去重。这些思路保留。

### D5 不继承旧告警桥接的命名漂移与无效开关

旧 `wingo` 分支的 `AnalysisAlertBridge` 有 3 个环境变量与 `config.py` 实际读取名不一致：

| 文档 / `.env.example` | `config.py` 实际读取 | 实际后果 |
| --- | --- | --- |
| `AGENT_ANALYSIS_ALERT_BRIDGE_EXPIRE_DAYS` | `AGENT_ANALYSIS_ALERT_EXPIRE_DAYS` | 按文档配置无效，永远 30 天 |
| `AGENT_ANALYSIS_ALERT_BRIDGE_SEVERITY` | `AGENT_ANALYSIS_ALERT_SEVERITY` | 永远 `warning`（且四个价位均写死字段级 severity，改名后仍不生效） |
| `AGENT_ANALYSIS_ALERT_BRIDGE_INCLUDE_SECONDARY_BUY` | `AGENT_ANALYSIS_ALERT_INCLUDE_SECONDARY_BUY` | 永远 `true`，无法关闭 `secondary_buy` |

新实现不搬运这些配置项：开关只保留"是否启用 + 规则过期天数"，severity 按信号语义固定，命名一次对齐 `.env.example` / `config_registry` / `settingsHelp.ts`，并由 `tests/test_config_registry.py` 持续校验。

## 6. 增量路线

| 步 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 领域层：`models` / `signals` / `features` + 单测 | 已完成 |
| 2 | 数据层：`data.py` + 单测 | 已完成 |
| 3 | 服务层 + 只读 API（默认关闭的配置开关） | 已完成 |
| 4 | 回测评估（复用 `BacktestEngine.evaluate_single`） | 待开始 |
| 5 | 告警联动（信号 → `price_cross` 规则，复用 alert 路由） | 已完成 |
| 6 | 前端最小页面 | 已完成 |
| 7 | 编排 / 日报 | 待开始 |
| 8 | 文档与 `docs/CHANGELOG.md` | 待开始 |

### 告警联动落地清单（第 5 步，已完成）

- `src/services/wyckoff/alerts.py`：
  - `build_rule_plans()` 纯函数把 `SignalRecord` 映射为规则计划，价位只取信号自身 K 线；
  - `WyckoffAlertBridge` 负责 `source="wyckoff"` 写入、按 `(code, direction, price)` 去重、单条失败降级；
  - `sync_wyckoff_alerts()` 是唯一编排入口，双开关（`WYCKOFF_ENABLED` + `WYCKOFF_ALERTS_ENABLED`）任一关闭即零副作用。
- 每个信号两条**独立**规则：`below` LPS 低点（`critical`，结构失效）与 `above` SOS 高点（`info`，放量确认）。方向与价位不同，语义 key 不同，可独立触发与冷却；信号日收盘已高于 SOS 高点时跳过确认规则，避免当天立即误触发。
- 有效期锚定信号触发日：`expires_at = trigger_date + WYCKOFF_ALERT_EXPIRE_DAYS`，`0` 表示永不过期；已过期信号不再补建规则。
- 告警中心新增 `expires_at`：DB 列（SQLite 增量迁移）+ `AlertService` 解析/序列化 + `AlertRepository.list_enabled_rules()` 过滤 + API 字段。
- 信号查询接口追加 `sos_high` / `trigger_low`（只增字段，不破坏旧客户端）。
- 通知投递零改动：worker 仍走 `route_type="alert"`，渠道由 `NOTIFICATION_ALERT_CHANNELS` 决定。

验证：

1. 单测 `tests/test_wyckoff_alerts.py`：两条规则独立、已突破跳过、非法价跳过、过期跳过、`0` 永不过期、重复同步幂等、单条失败非致命、开关关闭零副作用、`expires_at` 往返与过期规则不参与轮询。
2. 回归：`tests/test_alert_api.py`、`tests/test_alerts_docs.py`、`tests/test_config_registry.py`、`tests/test_config_env_compat.py` 全部通过。
3. 手工（需真实环境）：`AGENT_EVENT_MONITOR_ENABLED=true`、`WYCKOFF_ENABLED=true`、`WYCKOFF_ALERTS_ENABLED=true`、`EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECEIVERS`、`NOTIFICATION_ALERT_CHANNELS=email`，构造已穿越价位的规则跑一轮 worker，确认收到邮件且 `alert_trigger` / `alert_notification` 有记录。

### 前端落地清单（第 6 步，已完成）

- 路由与导航：`/wyckoff` 以路由级 `lazy()` 注册（`apps/dsa-web/src/App.tsx`），侧边栏与页面头部使用 `layout.nav.wyckoff` / `layout.route.wyckoff.*` 文案。
- `apps/dsa-web/src/pages/WyckoffPage.tsx`：
  - 左侧信号列表来自 `GET /api/v1/wyckoff/signals`，支持日期筛选、回到最新、刷新；展示信号日期、本地最新交易日、扫描数、无日线数。
  - 右侧个股详情来自 `GET /api/v1/wyckoff/detail/{code}?bars=180`，展示触发日 / SOS 日、收盘价、MA20、量比、SOS 高点、LPS 低点及 Spring / Test / 量价趋势特征。
  - 状态处理：403（`WYCKOFF_ENABLED` 关闭）显示未启用提示；`wyckoff_no_data`（404）显示空态；`is_stale` 显示"本地日线可能落后"提示。
- `apps/dsa-web/src/components/wyckoff/WyckoffChart.tsx`：按 D2 用 `echarts` 核心包按需注册（Candlestick / Line / Bar / Grid / Tooltip / AxisPointer / DataZoom / MarkPoint / MarkLine / CanvasRenderer），自建 `init` / `setOption` / `ResizeObserver` / `dispose` 封装。
  - 蜡烛 + MA20 + 成交量副图；窗口内触发点以 `LPS` 打点；选中信号绘制 SOS 高点（红虚线）与 LPS 低点（绿虚线）参考线。
  - 红涨绿跌，暗色/亮色主题下均使用同一组高对比常量色。
- `apps/dsa-web/src/api/wyckoff.ts` + `apps/dsa-web/src/types/wyckoff.ts`：复用 `apiClient` 与 `toCamelCase`，字段与 `api/v1/schemas/wyckoff.py` 一一对应。
- `apps/dsa-web/vite.config.ts`：`echarts` / `zrender` 单独分到 `vendor-echarts`，仅随 `/wyckoff` 懒加载，不进入首屏 `vendor`。

验证：

1. `npm run lint`、`npm run build` 通过；构建产物中 `vendor-echarts-*.js` 只被 `WyckoffPage-*.js` 动态引用，`vendor` 由 672K 降到 100K。
2. 新增 `src/api/__tests__/wyckoff.test.ts`（2 例：路径/参数与 snake_case 映射）与 `src/pages/__tests__/WyckoffPage.test.tsx`（3 例：列表选中并出图、403 未启用、陈旧 + 空信号）。
3. 全量 `npm test`：1385 passed；2 个既有失败（`tests/ui_governance.test.ts` 指向未改动的 `DesktopUpdateIndicator.tsx`，`DecisionSignalsPage` 过期信号刷新用例），与本次改动无关。
4. 未验证：真实浏览器交互与截图（按仓库要求，PR 需补受影响页面截图）；echarts 在真实数据密度下的缩放观感。

## 7. 未决事项

- 调度接入：`sync_wyckoff_alerts()` 已可独立调用，但尚未挂到每日任务（第 7 步），当前开启开关后需要手动触发同步。
- 前端只读：页面暂不支持从信号直接创建 / 查看关联告警规则，也没有回测入口（第 4 步）。
- 旧 `wingo` 分支的 3 个变量名漂移需在该分支修复（或随分支退役丢弃）；按当前边界不修改主工作区。
