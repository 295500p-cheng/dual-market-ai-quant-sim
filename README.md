# 双市场 AI 量化模拟投研平台

这是完整迁移包，包含网页、行情抓取、评分、模拟执行、模拟账户汇总、复盘、持仓、15天隔夜复盘、每日价格台账、周/月汇总、周回测、策略规则、股票池、台账和自动化任务模板。

## 重要说明

- 这是量化研究和模拟交易系统，不是真实券商交易系统。
- 不会真实下单，不会连接真实账户。
- 所有“买入、卖出、止盈、止损”都是模拟记录，用于复盘策略。
- A股和美股行情需要联网。

## 目录说明

- `outputs/quant-dual-market-site/`：网页前端。
- `outputs/daily-quant/`：策略、股票池、行情快照、推荐、模拟执行、复盘、周/月汇总、周回测和台账。
- `work/market-data/`：核心脚本。
- `scripts/`：常用启动和更新脚本。
- `automation-templates/`：原电脑上的定时任务模板。

## 环境要求

另一台电脑需要有：

- macOS 或 Linux。
- Python 3。
- Node.js 只用于检查网页脚本；不运行检查也可以不用。
- 能访问新浪财经和 Yahoo Finance。

## 第一次启动网站

进入本目录后运行：

```bash
chmod +x scripts/*.sh
./scripts/start_site.sh
```

然后浏览器打开：

```text
http://127.0.0.1:4174/quant-dual-market-site/
```

`start_site.sh` 会先把网页发布到 `/tmp/quant-site-public`，然后启动本地网页服务。

## A股盘中 15 分钟更新

```bash
./scripts/run_a_share_cycle.sh
```

会执行：

1. 更新行情。
2. 计算A股候选。
3. 模拟执行买入、持有、止盈、止损。
4. 刷新推荐跟踪和当前模拟持仓。
5. 发布网页数据。

## 美股盘中 15 分钟更新

```bash
./scripts/run_us_stock_cycle.sh
```

只建议在美股常规交易时段运行，避免盘前旧数据覆盖候选。

## A股收盘复盘

A股收盘后运行：

```bash
./scripts/run_a_share_review.sh
```

## 美股收盘复盘

美股收盘后运行：

```bash
./scripts/run_us_stock_review.sh
```

## 系统体检

```bash
./scripts/run_health_check.sh
```

会检查脚本、网页、行情源、A股评分、模拟执行、持仓、周回测和发布链路。

体检现在是只读检查：会验证脚本语法、必要文件、JSON/台账结构和行情源连通性，但不会写入候选台账、不会改变模拟持仓，也不会触发模拟买入或卖出。行情源暂时不可用时，会保留上一份有效行情并标记“需留意”。

首页“模拟账户总览”会显示最近一次自动行情刷新的结果。刷新失败时，本轮评分和模拟执行会自动停止，不会使用旧推荐价格推算成交。

## 周/月汇总分析

系统会自动生成：

```text
outputs/daily-quant/reviews/performance-summary.json
```

网页里的“周/月汇总”面板会展示：

- 近7天和本月的已复盘样本数、胜率、平均股票涨跌幅、平均隔夜收益和平均相对基准收益。
- 按股票汇总的推荐次数、已复盘次数、股票涨跌幅、隔夜收益、相对基准收益和策略胜率。
- 按策略标签汇总的推荐次数、已复盘次数、胜率、股票涨跌幅和相对基准收益。

胜率只统计真实已复盘且结果为“命中/失败”的样本；待复盘和数据不足不计入胜率。

## 15天隔夜复盘和每日股价

系统会自动生成：

```text
outputs/daily-quant/reviews/overnight-15d-backtest.json
outputs/daily-quant/reviews/price-history.csv
```

网页里的“15天复盘”面板会展示：

- 最近15天隔夜候选的推荐次数、已复盘次数、胜率、平均隔夜收益、收盘涨跌、相对基准和最大回撤。
- 可下拉切换全部、A股、美股和高隔夜评分候选。
- 可下拉选择单只股票，查看该股票的15天走势、推荐明细、次日开收盘、止盈止损、收益和复盘结论。
- 每日股价表会展示开盘、最高、最低、收盘或最新价、涨跌幅、来源时间；历史行情不足时，先用推荐记录里的推荐价补位，后续每次行情刷新会继续积累。

这仍然只用于模拟复盘，不代表真实买卖结果。

## 模拟账户总览

系统会自动生成：

```text
outputs/daily-quant/execution/portfolio-summary.json
```

首页会展示总资产、累计盈亏、可用现金、持仓数和今日模拟交易笔数；“模拟持仓”面板会逐只展示持仓数量、可用数量、成本金额、持仓市值、浮动盈亏和风控线。

默认计算口径：

- 初始模拟资金：100000。
- 单只股票目标模拟资金：10000；A股按100股一手取整，美股按整股取整，实际持仓成本可能高于或低于目标值。
- A股模拟执行遵循T+1，当日买入可用数量为0；美股按整股计算。
- 新增模拟买入必须同时满足持仓上限和可用模拟现金要求。
- A股和美股统一按模拟资金单位展示，不做真实汇率折算。
- 自动买入卖出只写入模拟台账，不连接券商、不真实下单。

## 自动化任务

`automation-templates/` 里保留了原电脑上的自动化任务模板：

- `a-15`：A股15分钟动态选股与隔夜策略监控。
- `15`：美股15分钟动态选股与隔夜策略监控。
- `a-2`：A股每日量化复盘与次日候选。
- `automation`：美股每日量化复盘与次日候选。

在另一台电脑上，如果继续使用 Codex 自动化，需要按新电脑的实际目录修改模板里的 `cwds` 路径。

## 核心策略位置

- 总目标：`outputs/daily-quant/final-objective.md`
- 更新规则：`outputs/daily-quant/config/update-rules.md`
- 策略规则库：`outputs/daily-quant/strategy-log/strategy-rules.md`
- 国内外系统学习对照：`outputs/daily-quant/strategy-log/system-study-matrix.md`
- A股股票池：`outputs/daily-quant/config/universe-a-share.csv`
- 美股股票池：`outputs/daily-quant/config/universe-us-stock.csv`
- 数据源说明：`outputs/daily-quant/config/data-sources.md`

## 当前数据会一起迁移

本包已包含当前：

- 最新候选。
- 行情快照。
- 模拟执行台账。
- 模拟账户汇总。
- 当前模拟持仓。
- 推荐跟踪。
- 每日复盘。
- 15天隔夜复盘。
- 每日价格台账。
- 周/月汇总。
- 周回测。

迁移后可以直接接着跑，不需要从零开始。
