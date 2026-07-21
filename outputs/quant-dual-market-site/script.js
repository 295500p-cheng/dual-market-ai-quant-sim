const canvas = document.querySelector("#equityChart");
const ctx = canvas.getContext("2d");
const overnightCanvas = document.querySelector("#overnightTrendChart");
const overnightCtx = overnightCanvas.getContext("2d");
const segments = document.querySelectorAll(".segment");
const densityToggle = document.querySelector("#densityToggle");
let activeMarket = "cn";
let latestStats = null;
let overnightBacktestData = null;

function applyDensity(enabled) {
  document.body.classList.toggle("compact-mode", enabled);
  if (densityToggle) densityToggle.checked = enabled;
  localStorage.setItem("quantDensity", enabled ? "compact" : "standard");
  drawChart(activeMarket);
  if (overnightBacktestData) drawOvernightTrend(selectedBacktestView()?.dailyRows ?? []);
}

const savedDensity = localStorage.getItem("quantDensity");
applyDensity(savedDensity ? savedDensity === "compact" : true);

if (densityToggle) {
  densityToggle.addEventListener("change", () => applyDensity(densityToggle.checked));
}

function drawChart(key) {
  const ratio = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth;
  const isCompact = document.body.classList.contains("compact-mode");
  const cssHeight = Math.round(cssWidth * (isCompact ? 0.34 : 0.395));
  canvas.width = Math.round(cssWidth * ratio);
  canvas.height = Math.round(cssHeight * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

  const width = cssWidth;
  const height = cssHeight;
  const pad = isCompact
    ? { top: 22, right: 22, bottom: 28, left: 34 }
    : { top: 28, right: 28, bottom: 34, left: 42 };

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#101716";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = pad.top + ((height - pad.top - pad.bottom) / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  ctx.fillStyle = "#dfe8e2";
  ctx.font = `700 ${isCompact ? 11 : 13}px Inter, Arial`;
  ctx.fillText(key === "cn" ? "A股真实回测状态" : "美股真实回测状态", pad.left, isCompact ? 15 : 18);
  ctx.fillStyle = "rgba(223,232,226,.62)";
  ctx.font = `700 ${isCompact ? 15 : 20}px Inter, Arial`;
  ctx.fillText("暂无真实回测曲线", pad.left, height / 2 - (isCompact ? 5 : 8));
  ctx.font = `${isCompact ? 11 : 13}px Inter, Arial`;
  ctx.fillText("开盘后15分钟动态选股和每日复盘会写入真实样本，再计算胜率、回撤和隔夜收益。", pad.left, height / 2 + (isCompact ? 18 : 22));
}

function setMarket(key) {
  activeMarket = key;
  updateHeroMetrics();
  segments.forEach((button) => button.classList.toggle("active", button.dataset.market === key));
  drawChart(key);
}

segments.forEach((button) => {
  button.addEventListener("click", () => setMarket(button.dataset.market));
});

window.addEventListener("resize", () => drawChart(activeMarket));
setMarket(activeMarket);

async function loadJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`无法读取 ${path}`);
  return response.json();
}

function metric(label, value) {
  return `<div><small>${label}</small><strong>${value ?? "待计算"}</strong></div>`;
}

function renderPickCard(pick) {
  return `
    <article>
      <b>${pick.symbol} ${pick.name}</b>
      <span>${pick.action} · 隔夜评分 ${pick.overnightScore ?? "待评分"}/100 · 行情 ${pick.sourceTimestamp || "待确认"}</span>
      <div class="pick-metrics">
        ${metric("当前价", pick.currentPrice)}
        ${metric("买入观察区", pick.buyZone)}
        ${metric("止盈", pick.takeProfit)}
        ${metric("止损", pick.stopLoss)}
      </div>
      <p><strong>卖出/放弃：</strong>${pick.sellRule}</p>
      <p><strong>隔夜判断：</strong>${pick.overnightView}</p>
      <p><strong>上涨逻辑：</strong>${pick.logic}</p>
      <p><strong>最大风险：</strong>${pick.risk}</p>
    </article>
  `;
}

function renderPickPanel(title, subtitle, picks) {
  const content = picks.length
    ? picks.map(renderPickCard).join("")
    : `<article><b>暂无真实动态推荐</b><span>等待可靠行情</span><p>没有当前价、成交量、相对强弱和事件风险校验前，不显示股票推荐。</p></article>`;
  return `
    <section class="pick-panel">
      <div class="pick-head">
        <span>${title}</span>
        <strong>${subtitle}</strong>
      </div>
      <div class="pick-list">
        ${content}
      </div>
    </section>
  `;
}

async function renderLivePicks() {
  const data = await loadJson("../daily-quant/live/latest-picks.json");
  document.querySelector("#liveStatus").textContent = `${data.status}：${data.note}`;
  document.querySelector("#liveUpdated").textContent = `更新时间：${data.updatedAt}`;
  const warning = document.querySelector("#modeWarning");
  const stateText = `${data.status} ${data.note}`;
  const isSimulation = stateText.includes("模拟");
  const isSnapshot = stateText.includes("快照") || stateText.includes("不是实时") || stateText.includes("非实时");
  const isWaiting = stateText.includes("休市") || stateText.includes("数据不足") || stateText.includes("待开盘");
  const needsWarning = isSimulation || isSnapshot || isWaiting;
  warning.hidden = !needsWarning;
  if (isSimulation) {
    warning.textContent = "当前为模拟演示：价格、评分、止盈止损和复盘结果都不是真实行情。";
  } else if (isSnapshot) {
    warning.textContent = "当前为行情源测试快照：用于检查数据源和评分链路，不等同于实时买卖建议。";
  } else if (isWaiting) {
    warning.textContent = "当前行情不完整：等开盘后拿到可核验价格、成交量和基准表现，再显示真实推荐。";
  } else {
    warning.textContent = "当前为真实数据模式：仅在行情字段完整且评分达标时显示股票。";
  }
  const aSharePicks = data.markets?.a_share ?? [];
  const usStockPicks = data.markets?.us_stock ?? [];
  document.querySelector("#livePickColumns").innerHTML = [
    renderPickPanel("A股", "15分钟动态评分", aSharePicks),
    renderPickPanel("美股", "15分钟动态评分", usStockPicks),
  ].join("");
}

function renderReviewRow(row) {
  return `
    <tr>
      <td><strong>${row.symbol}</strong><br>${row.name}</td>
      <td>${row.market}</td>
      <td>${row.previousCall}</td>
      <td>${row.openResult}</td>
      <td>${row.closeResult}</td>
      <td>${row.overnightReturn}</td>
      <td>${row.relativeReturn}</td>
      <td>${row.verdict}<br>${row.lesson}</td>
    </tr>
  `;
}

async function renderReview() {
  const data = await loadJson("../daily-quant/reviews/latest-review.json");
  document.querySelector("#reviewStatus").textContent = `${data.status}：${data.summary}`;
  document.querySelector("#reviewUpdated").textContent = `更新时间：${data.updatedAt}`;
  document.querySelector("#scoreSignal").textContent = data.scorecard.signalQuality;
  document.querySelector("#scoreOvernight").textContent = data.scorecard.overnightEffect;
  document.querySelector("#scoreRisk").textContent = data.scorecard.riskControl;
  document.querySelector("#scoreNext").textContent = data.scorecard.nextOptimization;
  document.querySelector("#reviewRows").innerHTML = data.rows.length
    ? data.rows.map(renderReviewRow).join("")
    : '<tr><td colspan="8">暂无真实复盘样本。第一轮动态推荐产生后，次日收盘再计算。</td></tr>';
}

function renderTrackerRow(row) {
  return `
    <tr>
      <td>${row.date}<br>${row.time}</td>
      <td><strong>${row.symbol}</strong><br>${row.name}<br>${row.market}</td>
      <td>${row.recommendedPrice}<br><span>${row.buyZone}</span></td>
      <td>${row.currentPrice}<br><span>${row.quoteDate}</span></td>
      <td><strong>${row.changeSinceCall}</strong></td>
      <td>${row.status}<br><span>${row.execution} / ${row.executionExit}</span></td>
      <td>${row.nextAction}</td>
    </tr>
  `;
}

async function renderTracker() {
  const data = await loadJson("../daily-quant/reviews/recommendation-tracker.json");
  const metrics = data.metrics;
  document.querySelector("#trackerStatus").textContent = `${data.status}：${data.summary}`;
  document.querySelector("#trackerUpdated").textContent = `更新时间：${data.updatedAt}`;
  document.querySelector("#trackerTotal").textContent = `${metrics.tracked} 条`;
  document.querySelector("#trackerPending").textContent = `${metrics.pending} 条`;
  document.querySelector("#trackerHolding").textContent = `${metrics.holding} 条`;
  document.querySelector("#trackerReviewed").textContent = `${metrics.reviewed} 条`;
  document.querySelector("#trackerRows").innerHTML = data.rows.length
    ? data.rows.map(renderTrackerRow).join("")
    : '<tr><td colspan="7">暂无推荐记录。下一轮推荐后会自动写入。</td></tr>';
}

function trendClass(value) {
  if (String(value).startsWith("+")) return "positive";
  if (String(value).startsWith("-")) return "negative";
  return "";
}

async function renderPortfolioSummary() {
  const data = await loadJson("../daily-quant/execution/portfolio-summary.json");
  const metrics = data.metrics ?? {};
  document.querySelector("#portfolioUpdated").textContent = `更新时间：${data.updatedAt}`;
  document.querySelector("#pfTotalAssets").textContent = metrics.totalAssets ?? "待计算";
  document.querySelector("#pfInitialCapital").textContent = `初始 ${metrics.initialCapital ?? "待计算"} · ${data.status}`;
  document.querySelector("#pfPnl").textContent = metrics.cumulativePnl ?? "待计算";
  document.querySelector("#pfPnl").className = trendClass(metrics.cumulativePnl);
  document.querySelector("#pfPnlPct").textContent =
    `累计 ${metrics.cumulativePnlPct ?? "待计算"} · 浮动 ${metrics.floatingPnl ?? "待计算"}`;
  document.querySelector("#pfPnlPct").className = trendClass(metrics.cumulativePnlPct);
  document.querySelector("#pfCash").textContent = metrics.availableCash ?? "待计算";
  document.querySelector("#pfCashRatio").textContent = metrics.fundingStatus ?? `现金占比 ${metrics.cashRatio ?? "待计算"}`;
  document.querySelector("#pfCashRatio").className = metrics.overLimit > 0 ? "negative" : "";
  const holdingsTarget = document.querySelector("#pfHoldings");
  holdingsTarget.textContent = `${metrics.holdings ?? 0} / ${metrics.maxHoldings ?? 0}`;
  holdingsTarget.className = metrics.overLimit > 0 ? "negative" : "";
  document.querySelector("#pfMarketValue").textContent =
    `持仓市值 ${metrics.marketValue ?? "待计算"} · 仓位 ${metrics.positionRatio ?? "待计算"}` +
    (metrics.overLimit > 0 ? ` · 历史遗留超限 ${metrics.overLimit} 只，已禁止新增` : "") +
    (metrics.historicalCorrections > 0 ? ` · 历史未成交校正 ${metrics.historicalCorrections} 条` : "");
  document.querySelector("#pfTodayTrades").textContent = `${metrics.todayTrades ?? 0}`;
  document.querySelector("#pfSignals").textContent =
    `买入 ${metrics.todayBuys ?? 0} / 退出 ${metrics.todayExits ?? 0} · 信号 ${metrics.signals ?? 0}`;
}

async function renderRefreshStatus() {
  const target = document.querySelector("#refreshStatus");
  try {
    const data = await loadJson("../daily-quant/live/last-fetch-status.json");
    const labels = { success: "成功", partial: "部分成功", failed: "失败保护" };
    target.className = `refresh-state ${data.status || "unknown"}`;
    target.textContent = `自动刷新：${labels[data.status] || "待确认"} · ${data.attemptedAt || "暂无时间"}`;
    target.title = data.message || "";
  } catch (error) {
    target.className = "refresh-state unknown";
    target.textContent = "自动刷新：暂无状态记录";
  }
}

function renderPositionRow(row) {
  const pnlClass = Number(row.floatingPnlAmountValue) > 0
    ? "positive"
    : Number(row.floatingPnlAmountValue) < 0
      ? "negative"
      : "";
  return `
    <tr>
      <td><strong>${row.symbol}</strong><br>${row.name}<br><span>${row.market}</span></td>
      <td><strong>${Number(row.quantity || 0).toLocaleString("zh-CN")} 股</strong><br><span>可用 ${Number(row.availableQuantity || 0).toLocaleString("zh-CN")} 股${row.frozenQuantity ? ` · 冻结 ${row.frozenQuantity}` : ""}</span></td>
      <td>${row.entryPrice}<br><span>${row.entryTime}</span></td>
      <td><strong>${row.currentPrice}</strong><br><span>昨收 ${row.previousClose} · ${row.quoteTime}</span></td>
      <td class="money-cell"><strong>${row.costAmount}</strong></td>
      <td class="money-cell"><strong>${row.marketValue}</strong></td>
      <td class="money-cell"><strong class="${pnlClass}">${row.floatingPnlAmount}</strong><br><span class="${trendClass(row.positionReturn)}">${row.positionReturn}</span></td>
      <td><strong class="${trendClass(row.dayReturn)}">${row.dayReturn}</strong></td>
      <td>止盈 ${row.takeProfit}<br>止损 ${row.stopLoss}<br><span>距止盈 ${row.takeProfitGap} / 距止损 ${row.stopBuffer}</span></td>
      <td>${row.status}<br><span>${row.nextAction}</span></td>
    </tr>
  `;
}

async function renderPositions() {
  const data = await loadJson("../daily-quant/execution/current-positions.json");
  const metrics = data.metrics;
  document.querySelector("#positionsStatus").textContent = `${data.status}：${data.summary}`;
  document.querySelector("#positionsUpdated").textContent = `更新时间：${data.updatedAt}`;
  document.querySelector("#posTotal").textContent = `${metrics.positions} 只`;
  document.querySelector("#posMarkets").textContent = `A股 ${metrics.aShare} / 美股 ${metrics.usStock}`;
  document.querySelector("#posCost").textContent = metrics.totalCost;
  document.querySelector("#posMarketValue").textContent = metrics.totalMarketValue;
  const pnlTarget = document.querySelector("#posPnl");
  pnlTarget.textContent = metrics.totalFloatingPnl;
  pnlTarget.className = Number(metrics.totalFloatingPnlValue) > 0
    ? "positive"
    : Number(metrics.totalFloatingPnlValue) < 0
      ? "negative"
      : "";
  document.querySelector("#posPnlDetail").textContent =
    `浮盈 ${metrics.winners} / 浮亏 ${metrics.losers} · T+1锁定 ${metrics.tPlusOneLocked}`;
  document.querySelector("#positionsRows").innerHTML = data.rows.length
    ? data.rows.map(renderPositionRow).join("")
    : '<tr><td colspan="10">暂无模拟持仓。等价格进入买入观察区后会自动出现。</td></tr>';
}

async function renderStats() {
  const data = await loadJson("../daily-quant/reviews/performance-stats.json");
  latestStats = data;
  const metrics = data.metrics;
  document.querySelector("#statTotalTrades").textContent = `${metrics.totalTrades} 笔`;
  document.querySelector("#statTotalWinRate").textContent = metrics.totalWinRate;
  document.querySelector("#statOvernightWinRate").textContent =
    `${metrics.overnightWinRate} / ${metrics.overnightTrades} 笔`;
  document.querySelector("#statMarketWinRate").textContent =
    `A股 ${metrics.aShareWinRate} / 美股 ${metrics.usStockWinRate}`;
  updateHeroMetrics();
}

function renderExecutionRow(row) {
  const entry = row.entry_price ? `${row.entry_status}<br>${row.entry_price}` : row.entry_status;
  const exit = row.exit_price ? `${row.exit_status}<br>${row.exit_price}` : row.exit_status;
  return `
    <tr>
      <td><strong>${row.symbol}</strong><br>${row.name}</td>
      <td>${row.market}</td>
      <td>${entry}</td>
      <td>${exit}</td>
      <td>${row.result_return || "待计算"}</td>
      <td>${row.risk_note}</td>
    </tr>
  `;
}

async function renderExecution() {
  const data = await loadJson("../daily-quant/execution/latest-executions.json");
  const metrics = data.metrics;
  document.querySelector("#executionStatus").textContent = `${data.status}：${data.note}`;
  document.querySelector("#executionUpdated").textContent = `更新时间：${data.updatedAt}`;
  document.querySelector("#execSignals").textContent = `${metrics.signals} 个`;
  document.querySelector("#execTriggered").textContent = `${metrics.triggered} 个`;
  document.querySelector("#execExited").textContent = `${metrics.exited} 个`;
  document.querySelector("#execWaiting").textContent = `${metrics.waiting} 个`;
  document.querySelector("#executionRows").innerHTML = data.rows.length
    ? data.rows.map(renderExecutionRow).join("")
    : '<tr><td colspan="6">暂无模拟执行记录。</td></tr>';
}

function renderWeeklyMarketRows(rows) {
  if (!rows?.length) {
    return '<div class="mini-row"><strong>暂无</strong><span>等待真实复盘样本</span><span></span><span></span><span></span></div>';
  }
  return rows
    .map(
      (row) => `
        <div class="mini-row">
          <strong>${row.market}</strong>
          <span>${row.reviewed} 笔</span>
          <span>胜率 ${row.winRate}</span>
          <span>隔夜 ${row.overnightAvg}</span>
          <span>相对 ${row.relativeAvg}</span>
        </div>
      `,
    )
    .join("");
}

async function renderWeeklyReview() {
  const data = await loadJson("../daily-quant/reviews/weekly-review.json");
  const metrics = data.metrics;
  document.querySelector("#weeklyStatus").textContent = `${data.status}：${data.summary}`;
  document.querySelector("#weeklyUpdated").textContent = `周期：${data.period} · 更新时间：${data.updatedAt}`;
  document.querySelector("#weeklyReviewed").textContent = `${metrics.reviewedTrades} 笔`;
  document.querySelector("#weeklyWinRate").textContent = metrics.weeklyWinRate;
  document.querySelector("#weeklyOvernight").textContent =
    `${metrics.overnightWinRate} / ${metrics.overnightTrades} 笔`;
  document.querySelector("#weeklyMarkets").textContent =
    `A股 ${metrics.aShareWinRate} / 美股 ${metrics.usStockWinRate}`;
  document.querySelector("#weeklyRelative").textContent = metrics.avgRelativeReturn;
  document.querySelector("#weeklyPending").textContent = `${metrics.pendingTrades} 条`;
  document.querySelector("#weeklyExecution").textContent =
    `${metrics.executionBuys ?? 0} 买入 / ${metrics.executionExits ?? 0} 退出`;
  document.querySelector("#weeklyMarketRows").innerHTML = renderWeeklyMarketRows(data.marketRows);
  document.querySelector("#weeklyFocus").innerHTML = (data.nextWeekFocus ?? [])
    .map((item) => `<li>${item}</li>`)
    .join("");
}

function renderPeriodCard(period) {
  const metrics = period.metrics;
  return `
    <article>
      <span>${period.label} · ${period.period}</span>
      <strong>${metrics.executionWinRate ?? "暂无"}</strong>
      <small>${metrics.executionTrades ?? 0} 笔模拟平仓 · 已实现盈亏 ${metrics.executionRealizedPnl ?? "暂无"} · 信号复盘胜率 ${metrics.candidateWinRate ?? metrics.winRate}</small>
    </article>
  `;
}

function renderSummaryStockRow(row) {
  return `
    <tr>
      <td><strong>${row.symbol}</strong><br>${row.name}</td>
      <td>${row.market}</td>
      <td>${row.calls} 次<br><span>${row.reviewed} 已复盘</span></td>
      <td><strong class="${trendClass(row.avgStockReturn)}">${row.avgStockReturn}</strong></td>
      <td><strong class="${trendClass(row.avgOvernightReturn)}">${row.avgOvernightReturn}</strong></td>
      <td><strong class="${trendClass(row.avgRelativeReturn)}">${row.avgRelativeReturn}</strong></td>
      <td>${row.winRate}</td>
      <td>${row.latestResult}</td>
    </tr>
  `;
}

function renderSummaryStrategyRow(row) {
  return `
    <tr>
      <td><strong>${row.strategy}</strong></td>
      <td>${row.calls} 次</td>
      <td>${row.reviewed} 笔</td>
      <td>${row.winRate}</td>
      <td><strong class="${trendClass(row.avgStockReturn)}">${row.avgStockReturn}</strong></td>
      <td><strong class="${trendClass(row.avgRelativeReturn)}">${row.avgRelativeReturn}</strong></td>
    </tr>
  `;
}

function renderPeriodSummary(period, stockTarget, strategyTarget, periodTarget) {
  document.querySelector(periodTarget).textContent = period.period;
  document.querySelector(stockTarget).innerHTML = period.stockRows?.length
    ? period.stockRows.map(renderSummaryStockRow).join("")
    : '<tr><td colspan="8">暂无已复盘股票样本。</td></tr>';
  document.querySelector(strategyTarget).innerHTML = period.strategyRows?.length
    ? period.strategyRows.map(renderSummaryStrategyRow).join("")
    : '<tr><td colspan="6">暂无已复盘策略样本。</td></tr>';
}

async function renderPerformanceSummary() {
  const data = await loadJson("../daily-quant/reviews/performance-summary.json");
  const weekly = data.periods?.find((period) => period.key === "weekly") ?? data.periods?.[0];
  const monthly = data.periods?.find((period) => period.key === "monthly") ?? data.periods?.[1];
  document.querySelector("#summaryStatus").textContent = `${data.status}：${data.summary}`;
  document.querySelector("#summaryUpdated").textContent = `更新时间：${data.updatedAt}`;
  document.querySelector("#periodSummaryCards").innerHTML = (data.periods ?? [])
    .map(renderPeriodCard)
    .join("");
  if (weekly) {
    renderPeriodSummary(weekly, "#weeklySummaryRows", "#weeklyStrategyRows", "#weeklySummaryPeriod");
  }
  if (monthly) {
    renderPeriodSummary(monthly, "#monthlySummaryRows", "#monthlyStrategyRows", "#monthlySummaryPeriod");
  }
}

function selectOptions(select, options, fallbackValue = "all") {
  const current = select.value || fallbackValue;
  select.innerHTML = options
    .map((option) => `<option value="${option.value}">${option.label}</option>`)
    .join("");
  select.value = options.some((option) => option.value === current) ? current : fallbackValue;
}

function backtestTrendClass(value) {
  return trendClass(value === "暂无" ? "" : value);
}

function drawOvernightTrend(rows = []) {
  const ratio = window.devicePixelRatio || 1;
  const cssWidth = overnightCanvas.clientWidth;
  const cssHeight = Math.round(cssWidth * 0.34);
  overnightCanvas.width = Math.round(cssWidth * ratio);
  overnightCanvas.height = Math.round(cssHeight * ratio);
  overnightCtx.setTransform(ratio, 0, 0, ratio, 0, 0);

  const width = cssWidth;
  const height = cssHeight;
  const pad = { top: 28, right: 24, bottom: 34, left: 44 };
  overnightCtx.clearRect(0, 0, width, height);
  overnightCtx.fillStyle = "#101716";
  overnightCtx.fillRect(0, 0, width, height);

  overnightCtx.strokeStyle = "rgba(255,255,255,.08)";
  overnightCtx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = pad.top + ((height - pad.top - pad.bottom) / 4) * i;
    overnightCtx.beginPath();
    overnightCtx.moveTo(pad.left, y);
    overnightCtx.lineTo(width - pad.right, y);
    overnightCtx.stroke();
  }

  const values = rows.map((row) => Number(row.equityValue)).filter((value) => Number.isFinite(value));
  overnightCtx.fillStyle = "#dfe8e2";
  overnightCtx.font = "700 13px Inter, Arial";
  overnightCtx.fillText("15天净值走势", pad.left, 18);
  if (!values.length) {
    overnightCtx.fillStyle = "rgba(223,232,226,.66)";
    overnightCtx.font = "700 18px Inter, Arial";
    overnightCtx.fillText("暂无可绘制样本", pad.left, height / 2);
    return;
  }
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const spread = Math.max(1, maxValue - minValue);
  const low = minValue - spread * 0.15;
  const high = maxValue + spread * 0.15;
  const xStep = values.length <= 1 ? 0 : (width - pad.left - pad.right) / (values.length - 1);
  const yFor = (value) => pad.top + (high - value) / (high - low) * (height - pad.top - pad.bottom);

  overnightCtx.strokeStyle = "#7fe0ac";
  overnightCtx.lineWidth = 2.5;
  overnightCtx.beginPath();
  values.forEach((value, index) => {
    const x = pad.left + xStep * index;
    const y = yFor(value);
    if (index === 0) overnightCtx.moveTo(x, y);
    else overnightCtx.lineTo(x, y);
  });
  overnightCtx.stroke();

  overnightCtx.fillStyle = "#f3f0dd";
  values.forEach((value, index) => {
    const x = pad.left + xStep * index;
    const y = yFor(value);
    overnightCtx.beginPath();
    overnightCtx.arc(x, y, 3, 0, Math.PI * 2);
    overnightCtx.fill();
  });

  overnightCtx.fillStyle = "rgba(223,232,226,.66)";
  overnightCtx.font = "12px Inter, Arial";
  overnightCtx.fillText(`起点 ${values[0].toFixed(2)} / 当前 ${values[values.length - 1].toFixed(2)}`, pad.left, height - 11);
}

function renderOvernightDailyRow(row) {
  const stockInfo = row.stocks?.items?.length
    ? [
        row.stocks.items
          .map(
            (item) =>
              `<span class="daily-stock-chip">${item.symbol} ${item.name}<small>${item.market} · ${item.result}</small></span>`,
          )
          .join(""),
        row.stocks.more ? `<span class="daily-stock-more">另有 ${row.stocks.more} 只</span>` : "",
      ].join("")
    : '<span class="daily-stock-empty">当日无隔夜候选</span>';
  return `
    <tr>
      <td>${row.date}</td>
      <td><div class="daily-stock-list">${stockInfo}</div></td>
      <td>${row.calls} 条<br><span>${row.pending} 待复盘</span></td>
      <td>${row.reviewed} 笔</td>
      <td>${row.winRate}</td>
      <td><strong class="${backtestTrendClass(row.avgOvernightReturn)}">${row.avgOvernightReturn}</strong></td>
      <td><strong class="${backtestTrendClass(row.avgCloseReturn)}">${row.avgCloseReturn}</strong></td>
      <td><strong class="${backtestTrendClass(row.avgRelativeReturn)}">${row.avgRelativeReturn}</strong></td>
      <td>${row.equity}</td>
    </tr>
  `;
}

function renderOvernightCallRow(row) {
  return `
    <tr>
      <td>${row.date}<br><span>${row.time}</span></td>
      <td><strong>${row.symbol}</strong><br>${row.name}<br><span>${row.market} · 隔夜评分 ${row.overnightScore}</span></td>
      <td>${row.action}</td>
      <td>${row.recommendedPrice}<br><span>${row.buyZone}</span></td>
      <td>止盈 ${row.takeProfit}<br>止损 ${row.stopLoss}</td>
      <td>开 ${row.nextOpen}<br>收 ${row.nextClose}</td>
      <td>隔夜 <strong class="${backtestTrendClass(row.overnightReturn)}">${row.overnightReturn}</strong><br>收盘 <strong class="${backtestTrendClass(row.closeReturn)}">${row.closeReturn}</strong><br>相对 ${row.relativeReturn}</td>
      <td>${row.result}<br><span>${row.lesson}</span></td>
    </tr>
  `;
}

function renderOvernightPriceRow(row) {
  return `
    <tr>
      <td>${row.date}</td>
      <td><strong>${row.symbol}</strong><br>${row.name}<br><span>${row.market}</span></td>
      <td>${row.open}</td>
      <td>${row.high}</td>
      <td>${row.low}</td>
      <td><strong>${row.close}</strong><br><span>前收 ${row.previousClose}</span></td>
      <td><strong class="${backtestTrendClass(row.changePct)}">${row.changePct}</strong></td>
      <td>${row.volume}</td>
      <td>${row.source}<br><span>${row.quoteTime}</span></td>
    </tr>
  `;
}

function selectedBacktestView() {
  if (!overnightBacktestData) return null;
  const filter = document.querySelector("#overnightBacktestFilter").value || "all";
  const stock = document.querySelector("#overnightBacktestStock").value || "all";
  const bucket = overnightBacktestData.buckets?.[filter] ?? overnightBacktestData.buckets?.all;
  if (stock !== "all" && overnightBacktestData.stocks?.[stock]) {
    const detail = overnightBacktestData.stocks[stock];
    return {
      bucket,
      metrics: detail.metrics,
      dailyRows: detail.dailyRows,
      callRows: detail.callRows,
      priceRows: detail.priceRows,
      stock,
    };
  }
  const stockKeys = new Set((bucket?.stockRows ?? []).map((row) => row.key));
  const callRows = Object.values(overnightBacktestData.stocks ?? {})
    .filter((stockItem) => stockKeys.has(stockItem.key))
    .flatMap((stockItem) => stockItem.callRows ?? [])
    .sort((a, b) => `${b.date} ${b.time}`.localeCompare(`${a.date} ${a.time}`))
    .slice(0, 60);
  const priceRows = Object.values(overnightBacktestData.stocks ?? {})
    .filter((stockItem) => stockKeys.has(stockItem.key))
    .flatMap((stockItem) => stockItem.priceRows ?? [])
    .sort((a, b) => {
      const dateCompare = b.date.localeCompare(a.date);
      if (dateCompare) return dateCompare;
      const sourceCompare = (a.source === "推荐记录" ? 1 : 0) - (b.source === "推荐记录" ? 1 : 0);
      if (sourceCompare) return sourceCompare;
      return a.symbol.localeCompare(b.symbol);
    })
    .slice(0, 80);
  return {
    bucket,
    metrics: bucket?.metrics,
    dailyRows: bucket?.dailyRows ?? [],
    callRows,
    priceRows,
    stock,
  };
}

function renderOvernightBacktestView() {
  const view = selectedBacktestView();
  if (!view?.bucket) return;
  const stockSelect = document.querySelector("#overnightBacktestStock");
  const stockOptions = [
    { value: "all", label: "全部股票" },
    ...(view.bucket.stockRows ?? []).map((row) => ({
      value: row.key,
      label: `${row.market} ${row.symbol} ${row.name}`,
    })),
  ];
  selectOptions(stockSelect, stockOptions);
  const refreshedView = selectedBacktestView();
  const metrics = refreshedView.metrics ?? {};

  document.querySelector("#overnightBtCalls").textContent = `${metrics.calls ?? 0} 条`;
  document.querySelector("#overnightBtReviewed").textContent = `${metrics.reviewed ?? 0} 笔`;
  document.querySelector("#overnightBtWinRate").textContent = metrics.winRate ?? "暂无";
  document.querySelector("#overnightBtOvernight").textContent = metrics.avgOvernightReturn ?? "暂无";
  document.querySelector("#overnightBtClose").textContent = metrics.avgCloseReturn ?? "暂无";
  document.querySelector("#overnightBtDrawdown").textContent = metrics.maxDrawdown ?? "暂无";
  document.querySelector("#overnightBtPending").textContent = `${metrics.pending ?? 0} 条`;
  document.querySelector("#overnightBtBest").textContent = metrics.bestStock ?? "暂无";
  document.querySelector("#overnightBtWeak").textContent = metrics.weakStock ?? "暂无";

  drawOvernightTrend(refreshedView.dailyRows ?? []);
  document.querySelector("#overnightDailyRows").innerHTML = refreshedView.dailyRows?.length
    ? refreshedView.dailyRows.map(renderOvernightDailyRow).join("")
    : '<tr><td colspan="9">暂无15天隔夜复盘样本。</td></tr>';
  document.querySelector("#overnightCallRows").innerHTML = refreshedView.callRows?.length
    ? refreshedView.callRows.map(renderOvernightCallRow).join("")
    : '<tr><td colspan="8">暂无所选范围的推荐明细。</td></tr>';
  document.querySelector("#overnightPriceRows").innerHTML = refreshedView.priceRows?.length
    ? refreshedView.priceRows.map(renderOvernightPriceRow).join("")
    : '<tr><td colspan="9">暂无每日价格记录；后续每次行情刷新会自动积累。</td></tr>';
}

async function renderOvernightBacktest() {
  const data = await loadJson("../daily-quant/reviews/overnight-15d-backtest.json");
  overnightBacktestData = data;
  document.querySelector("#overnightBacktestStatus").textContent = `${data.status}：${data.summary}`;
  document.querySelector("#overnightBacktestUpdated").textContent = `周期：${data.window} · 更新时间：${data.updatedAt}`;
  document.querySelector("#overnightBtWindow").textContent = data.window;
  selectOptions(
    document.querySelector("#overnightBacktestFilter"),
    (data.filters ?? [{ key: "all", label: "全部" }]).map((item) => ({ value: item.key, label: item.label })),
  );
  renderOvernightBacktestView();
}

function updateHeroMetrics() {
  const metrics = latestStats?.metrics;
  if (!metrics) {
    document.querySelector('[data-field="win"]').textContent = "暂无";
    document.querySelector('[data-field="drawdown"]').textContent = "暂无";
    document.querySelector('[data-field="holding"]').textContent = "0";
    document.querySelector('[data-field="risk"]').textContent = "待开盘";
    return;
  }
  const marketWinRate = activeMarket === "cn" ? metrics.aShareWinRate : metrics.usStockWinRate;
  const marketTrades = activeMarket === "cn" ? metrics.aShareTrades : metrics.usStockTrades;
  document.querySelector('[data-field="win"]').textContent = marketWinRate;
  document.querySelector('[data-field="drawdown"]').textContent = "暂无";
  document.querySelector('[data-field="holding"]').textContent = `${marketTrades} 笔`;
  document.querySelector('[data-field="risk"]').textContent = latestStats.status;
}

async function refreshLivePanels() {
  const settle = async (render, target, message) => {
    try {
      await render();
    } catch (error) {
      const element = document.querySelector(target);
      if (element) element.textContent = message;
    }
  };
  await Promise.all([
    settle(renderLivePicks, "#liveStatus", "推荐数据读取失败，请确认本地预览服务仍在运行。"),
    renderRefreshStatus(),
    settle(renderPortfolioSummary, "#portfolioUpdated", "模拟账户数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderTracker, "#trackerStatus", "推荐跟踪数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderPositions, "#positionsStatus", "模拟持仓数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderExecution, "#executionStatus", "模拟执行数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderReview, "#reviewStatus", "复盘数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderStats, "#reviewStatus", "胜率数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderWeeklyReview, "#weeklyStatus", "周回测数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderPerformanceSummary, "#summaryStatus", "周/月汇总数据读取失败，请确认本地预览服务仍在运行。"),
    settle(renderOvernightBacktest, "#overnightBacktestStatus", "15天隔夜复盘数据读取失败，请确认本地预览服务仍在运行。"),
  ]);
}

document.querySelector("#overnightBacktestFilter").addEventListener("change", renderOvernightBacktestView);
document.querySelector("#overnightBacktestStock").addEventListener("change", renderOvernightBacktestView);
window.addEventListener("resize", () => {
  if (overnightBacktestData) drawOvernightTrend(selectedBacktestView()?.dailyRows ?? []);
});

refreshLivePanels();
setInterval(refreshLivePanels, 60000);
