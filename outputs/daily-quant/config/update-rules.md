# 自动化更新规则

## 1. 每15分钟动态选股

每轮顺序：

1. 读取股票池：
   - A股：`outputs/daily-quant/config/universe-a-share.csv`
   - 美股：`outputs/daily-quant/config/universe-us-stock.csv`
   - 基准：`outputs/daily-quant/config/benchmarks.csv`

2. 获取行情与风险字段：
   - A股优先使用新浪财经 `hq.sinajs.cn`，读取股票、指数和 ETF 基准。
   - 美股优先使用 Yahoo Finance chart API，读取股票、ETF 基准和 `^VIX`。
   - 行情抓取先写入 `outputs/daily-quant/live/market-snapshot.json`。
   - 按 `outputs/daily-quant/config/data-fields.md` 要求检查。
   - 缺当前价、时间戳、成交量、基准表现时，不输出真实推荐。
   - A股任务只刷新A股行情，美股任务只刷新美股行情；另一市场保留最近一份有效记录，避免互相覆盖。
   - 行情请求完全失败时，不覆盖现有行情快照，并立即停止本轮评分和模拟执行。
   - 最近一次刷新状态写入 `outputs/daily-quant/live/last-fetch-status.json`，供首页显示成功、部分成功或失败保护。

3. 计算评分：
   - 评分前必须确认股票不是 ETF 或指数。
   - 趋势强度 20。
   - 量价配合 15。
   - 相对强弱 20。
   - 板块共振 15。
   - 事件风险 10。
   - 隔夜适配 20。

4. 筛选候选：
   - 总分 >= 70 才能进入主候选。
   - 每个市场最多显示 3-5 只。
   - 高风险股票必须明确标高风险。
   - ETF 只能做基准，不作为核心股票推荐。

5. 写入网站数据：
   - 更新 `outputs/daily-quant/live/latest-picks.json`。
   - 每只股票必须包含：当前价、买入观察区、止盈、止损、卖出/放弃条件、日内评分、隔夜评分、上涨逻辑、最大风险。
   - 非交易日或行情时间戳停留在上一交易日时，状态必须写成“行情快照/不是实时推荐”。

6. 写入台账：
   - 追加到 `outputs/daily-quant/strategy-log/candidate-ledger.csv`。
   - 用于收盘后复盘。

7. 自动模拟执行：
   - 推荐写入后执行 `python3 work/market-data/simulate_execution.py`。
   - 只做模拟，不连接券商，不真实下单。
   - 当前价进入买入观察区才记录“模拟买入”。
   - 已模拟买入的股票，在后续 15 分钟更新里继续跟踪；当前价触及止盈或止损后才记录“模拟退出”。
   - 不允许使用推荐前已经发生的日内高点/低点倒推成交。
   - 不允许使用旧推荐卡片里的价格代替当日行情；缺少当日可核验行情时必须标记“数据不足”，不得模拟成交。
   - 模拟账户最多新增到 10 只持仓；达到上限后，新信号只跟踪、不新增模拟买入。
   - 新增模拟买入前必须检查可用模拟现金；不足以买入最小交易单位时，只保留信号，不生成模拟成交。
   - 模拟账户禁止融资、禁止负现金、禁止超过10只持仓；持仓总成本不得超过扣除已实现盈亏后的可用模拟本金。
   - A股按100股一手计算模拟数量，并执行T+1：当日买入的可用数量为0，不允许同日模拟卖出；美股按整股计算。
   - 已有模拟持仓即使不再进入最新候选，也必须继续显示和检查止盈止损，不能从面板静默消失。
   - 历史遗留的超限仓位不做倒推删除，按后续可核验行情和原止盈止损规则逐步退出。
   - 旧版本中无法满足现金和最小交易单位约束的“已持仓”记录，追加“历史资金校正”审计记录并改作未成交观察，不计入持仓、市值或盈亏；不得删除原始台账。
   - 历史超限仓位造成的模拟资金缺口不得显示为用户欠款；可用现金最低显示为0，并单列“历史模拟资金超额（非欠款）”。
   - 写入 `outputs/daily-quant/execution/latest-executions.json` 和 `outputs/daily-quant/execution/execution-ledger.csv`。

8. 推荐跟踪：
   - 每轮推荐和模拟执行后执行 `python3 work/market-data/build_tracking.py`。
   - 写入 `outputs/daily-quant/reviews/recommendation-tracker.json`。
   - 用于页面展示历史推荐、推荐价、当前价、涨跌、执行状态和下一步复盘动作。

9. 当前模拟持仓：
   - 每轮模拟执行后执行 `python3 work/market-data/build_positions.py`。
   - 写入 `outputs/daily-quant/execution/current-positions.json`。
   - 只展示仍处于“模拟持有”的股票，包含持仓数量、可用数量、成本价、当前价、持仓成本、持仓市值、浮动盈亏、止盈止损和下一步动作。

10. 发布到本地预览：
   - 每轮数据刷新后执行 `python3 work/market-data/publish_site.py`。
   - 同步到 `/tmp/quant-site-public`，供 `http://127.0.0.1:4174/quant-dual-market-site/` 读取。

## 2. 收盘后复盘

每天收盘后：

1. 先更新行情快照：`python3 work/market-data/fetch_market_data.py`。
2. 再补齐收盘前模拟执行状态：
   - A股：`python3 work/market-data/simulate_execution.py --market a_share`
   - 美股：`python3 work/market-data/simulate_execution.py --market us_stock`
3. 再执行复盘脚本：
   - A股：`python3 work/market-data/review_candidates.py --market a_share`
   - 美股：`python3 work/market-data/review_candidates.py --market us_stock`
4. 读取当天所有盘中候选。
5. 读取 `outputs/daily-quant/execution/execution-ledger.csv`，确认哪些候选真实触发了模拟买入、止盈、止损或继续持有。
6. 补充开盘价、收盘价、次日开盘价。
7. 计算：
   - 隔夜收益。
   - 日内收益。
   - 相对基准收益。
   - 是否触发买入观察区。
   - 是否触发止盈/止损/放弃条件。
8. 写入 `outputs/daily-quant/reviews/latest-review.json`。
9. 重新计算 `outputs/daily-quant/reviews/performance-stats.json`。
10. 执行 `python3 work/market-data/build_tracking.py`，刷新推荐跟踪面板。
11. 执行 `python3 work/market-data/build_positions.py`，刷新当前模拟持仓面板。
12. 执行 `python3 work/market-data/publish_site.py`，刷新本地预览页面数据。
13. 生成下一交易日观察方向。

胜率只统计真实已复盘且触发交易结果的样本；未触发买入观察区的候选保留在复盘说明里，但不计入胜率。

## 3. 每日策略优化

复盘后只允许小步修改：

- 连续有效的因子升权。
- 连续失效的因子降权。
- 发现重大风险的股票临时剔除。
- 高波动隔夜失败时降低隔夜评分。
- 强于基准但未上涨的样本保留观察，不直接删除。

## 4. 每周回测

每周收盘后汇总一次：

1. 读取 `outputs/daily-quant/strategy-log/candidate-ledger.csv`。
2. 读取 `outputs/daily-quant/execution/execution-ledger.csv`。
3. 执行 `python3 work/market-data/weekly_review.py`。
4. 只统计真实已复盘且触发交易结果的样本。
5. 输出：
   - 本周胜率。
   - 本周隔夜胜率。
   - A股和美股市场胜率对比。
   - 模拟买入、持有、止盈、止损和等待触发数量。
   - 平均相对基准收益。
   - 最有效和最弱的策略标签。
   - 下周优化重点。
6. 写入 `outputs/daily-quant/reviews/weekly-review.json`。
7. 执行 `python3 work/market-data/publish_site.py`，刷新本地预览页面数据。

没有足够真实样本时，只显示“等待一周真实样本”，不使用模拟结果。

## 5. 暂停真实推荐条件

出现以下情况，只显示“数据不足/风险过高”：

- 关键行情缺失。
- 行情时间戳过旧。
- A股涨跌停导致无法合理成交。
- A股停牌或临近重大公告。
- 美股财报前后跳空风险过高。
- VIX 快速上行或市场系统性风险升高。
- 候选没有明显强于基准。

## 6. 页面展示规则

页面不允许展示假胜率、假回撤、假净值。

允许展示：

- 明确标注的模拟演示。
- 真实行情驱动的动态推荐。
- 真实复盘计算结果。
- 数据不足或风险过高的空状态。

## 7. 学习对照维护

- 国内外优秀系统学习记录写入 `outputs/daily-quant/strategy-log/system-study-matrix.md`。
- 页面只展示“学到的流程、已采纳功能、下一步”，不展示任何平台的收益承诺。
- 策略来源用于改进流程和风控，不用于证明某只股票一定会上涨。
- 每周复盘后，如果有新的有效经验或失效经验，更新学习对照表和策略规则库。
