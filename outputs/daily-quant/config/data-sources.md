# 行情数据源测试记录

## 当前结论

- A股：优先使用新浪财经 `https://hq.sinajs.cn/list=...`。
- 美股：优先使用 Yahoo Finance chart API `https://query1.finance.yahoo.com/v8/finance/chart/...`。
- ETF 和指数只做基准，不作为核心股票推荐。
- 非交易日拿到的是最近交易日快照，必须标注“不是实时推荐”。

## A股接口

测试通过：

- 数据源：新浪财经 `hq.sinajs.cn`。
- 请求要求：带 `User-Agent` 和 `Referer: https://finance.sina.com.cn`。
- 编码：GBK。
- 已验证字段：名称、开盘价、昨收、当前价、最高价、最低价、成交量、成交额、日期、时间。
- 当前用途：股票候选、沪深300、创业板指、科创50、中证500、ETF 基准。

注意：

- 免费接口不是交易所官方源，需要做时间戳校验。
- 周末/休市时返回最近交易日行情，只能做快照测试。

## 美股接口

测试通过：

- 数据源：Yahoo Finance chart API。
- 已验证字段：当前价、昨收、开盘、最高、最低、成交量、交易时间。
- `^VIX` 必须用指数符号并做 URL 编码。

注意：

- Yahoo quote 接口容易限流，当前不作为主源。
- 美股财报、盘前盘后新闻和 VIX 风险必须额外过滤。

## 输出文件

- 行情快照：`outputs/daily-quant/live/market-snapshot.json`
- 动态候选：`outputs/daily-quant/live/latest-picks.json`
- 评分审计：`outputs/daily-quant/strategy-log/last-score-audit.json`
