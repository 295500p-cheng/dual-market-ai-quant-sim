# 双市场 AI 量化模拟投研平台

这是完整迁移包，包含网页、行情抓取、评分、模拟执行、复盘、持仓、周回测、策略规则、股票池、台账和自动化任务模板。

## 重要说明

- 这是量化研究和模拟交易系统，不是真实券商交易系统。
- 不会真实下单，不会连接真实账户。
- 所有“买入、卖出、止盈、止损”都是模拟记录，用于复盘策略。
- A股和美股行情需要联网。

## 目录说明

- `outputs/quant-dual-market-site/`：网页前端。
- `outputs/daily-quant/`：策略、股票池、行情快照、推荐、模拟执行、复盘、周回测和台账。
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
- 当前模拟持仓。
- 推荐跟踪。
- 每日复盘。
- 周回测。

迁移后可以直接接着跑，不需要从零开始。
