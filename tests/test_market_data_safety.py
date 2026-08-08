import importlib.util
import sys
import tempfile
import unittest
from datetime import date, datetime
from datetime import timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "work" / "market-data"))


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load_module("fetch_market_data", "work/market-data/fetch_market_data.py")
execution = load_module("simulate_execution", "work/market-data/simulate_execution.py")
portfolio = load_module("portfolio_summary", "work/market-data/portfolio_summary.py")
sizing = load_module("position_sizing", "work/market-data/position_sizing.py")
normalizer = load_module("normalize_legacy_positions", "work/market-data/normalize_legacy_positions.py")
performance = load_module("performance_summary", "work/market-data/performance_summary.py")
overnight = load_module("overnight_backtest", "work/market-data/overnight_backtest.py")
cloud_schedule = load_module("cloud_schedule", "work/market-data/cloud_schedule.py")
review = load_module("review_candidates", "work/market-data/review_candidates.py")
weekly = load_module("weekly_review", "work/market-data/weekly_review.py")


class MarketDataSafetyTests(unittest.TestCase):
    def setUp(self):
        self.pick = {
            "market": "A股",
            "symbol": "000001",
            "name": "测试股票",
            "action": "盘中：强势观察",
            "dayScore": 85,
            "overnightScore": 75,
            "currentPrice": "当前 100.00",
            "buyZone": "99.00-101.00",
            "takeProfit": "104.00-105.00",
            "stopLoss": "97.00",
        }

    def execute(self, quote):
        return execution.simulated_execution(
            self.pick,
            quote,
            "盘中可核验行情候选",
            "2026-07-13T09:30:00",
        )

    def test_missing_quote_never_uses_pick_price(self):
        row = self.execute({})
        self.assertEqual(row["entry_status"], "数据不足")
        self.assertEqual(row["current_price"], "")

    def test_stale_quote_cannot_trigger_simulated_buy(self):
        row = self.execute({"current_price": 100, "timestamp": "2020-01-01 10:00:00"})
        self.assertEqual(row["entry_status"], "数据不足")

    def test_same_day_but_old_quote_cannot_trigger_simulated_buy(self):
        now = datetime.now(execution.CHINA_TZ)
        old = now.replace(hour=9, minute=30, second=0, microsecond=0)
        if (now - old).total_seconds() <= 35 * 60:
            old = old.replace(day=max(1, old.day - 1))
        row = self.execute({"current_price": 100, "timestamp": old.strftime("%Y-%m-%d %H:%M:%S")})
        self.assertEqual(row["entry_status"], "数据不足")

    def test_current_quote_can_trigger_simulated_buy(self):
        timestamp = datetime.now(execution.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        row = self.execute({"current_price": 100, "timestamp": timestamp})
        self.assertEqual(row["entry_status"], "模拟买入")
        self.assertEqual(row["entry_price"], "100.00")

    def test_test_snapshot_never_triggers_simulated_buy(self):
        timestamp = datetime.now(execution.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        row = execution.simulated_execution(
            self.pick,
            {"current_price": 100, "timestamp": timestamp},
            "行情源测试快照，不是实时推荐",
            "2026-07-13T09:30:00",
        )
        self.assertEqual(row["entry_status"], "等待触发")
        self.assertIn("不是当轮可核验", row["risk_note"])

    def test_us_candidate_observation_never_triggers_simulated_buy(self):
        timestamp = datetime.now(execution.US_TZ).isoformat(timespec="seconds")
        pick = {**self.pick, "market": "美股", "action": "盘中：候选观察"}
        row = execution.simulated_execution(
            pick,
            {"current_price": 100, "timestamp": timestamp},
            "开盘后可核验行情候选",
            "2026-07-13T09:30:00",
        )
        self.assertEqual(row["entry_status"], "等待触发")
        self.assertIn("仅允许强势观察", row["risk_note"])

    def test_high_risk_strong_signal_never_triggers_simulated_buy(self):
        timestamp = datetime.now(execution.US_TZ).isoformat(timespec="seconds")
        pick = {**self.pick, "market": "美股", "action": "盘中：高风险强势观察"}
        row = execution.simulated_execution(
            pick,
            {"current_price": 100, "timestamp": timestamp},
            "开盘后可核验行情候选",
            "2026-07-13T09:30:00",
        )
        self.assertEqual(row["entry_status"], "等待触发")
        self.assertIn("高风险", row["risk_note"])

    def test_low_score_strong_signal_never_triggers_simulated_buy(self):
        timestamp = datetime.now(execution.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        pick = {**self.pick, "dayScore": 81}
        row = execution.simulated_execution(
            pick,
            {"current_price": 100, "timestamp": timestamp},
            "盘中可核验行情候选",
            "2026-07-13T09:30:00",
        )
        self.assertEqual(row["entry_status"], "等待触发")
        self.assertIn("低于82", row["risk_note"])

    def test_position_limit_blocks_new_simulated_buy(self):
        timestamp = datetime.now(execution.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        row = execution.simulated_execution(
            self.pick,
            {"current_price": 100, "timestamp": timestamp},
            "盘中可核验行情候选",
            "2026-07-13T09:30:00",
            can_open=False,
        )
        self.assertEqual(row["entry_status"], "等待触发")
        self.assertIn("持仓已达到上限", row["risk_note"])

    def test_cash_limit_uses_specific_block_reason(self):
        timestamp = datetime.now(execution.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        reason = "可用模拟现金不足：只保留信号，不模拟买入。"
        row = execution.simulated_execution(
            self.pick,
            {"current_price": 100, "timestamp": timestamp},
            "盘中可核验行情候选",
            "2026-07-13T09:30:00",
            can_open=False,
            open_block_reason=reason,
        )
        self.assertEqual(row["entry_status"], "等待触发")
        self.assertEqual(row["risk_note"], reason)

    def test_a_share_quantity_uses_board_lot(self):
        self.assertEqual(sizing.simulated_quantity("A股", 80.0), 100)
        self.assertEqual(sizing.simulated_quantity("A股", 37.25), 200)
        self.assertEqual(sizing.simulated_quantity("美股", 242.67), 41)

    def test_new_a_share_order_never_exceeds_position_cap(self):
        self.assertEqual(sizing.entry_order_quantity("A股", 80.0), 100)
        self.assertEqual(sizing.entry_order_quantity("A股", 120.0), 0)
        self.assertEqual(sizing.entry_order_cost("A股", 120.0), 0)
        self.assertEqual(sizing.entry_order_quantity("美股", 12_000.0), 0)
        self.assertEqual(sizing.simulated_quantity("A股", 120.0), 100)

    def test_current_rule_metrics_separate_legacy_account_loss(self):
        rows = [
            {
                "updated_at": "2026-07-22T10:00:00",
                "market": "美股",
                "symbol": "WIN",
                "name": "Winner",
                "entry_status": "模拟买入",
                "exit_status": "模拟持有",
                "entry_price": "100.00",
                "source_status": "开盘后可核验行情候选",
                "action": "盘中：强势观察",
            },
            {
                "updated_at": "2026-07-23T10:00:00",
                "market": "美股",
                "symbol": "WIN",
                "name": "Winner",
                "entry_status": "已持仓",
                "exit_status": "模拟止盈",
                "entry_price": "100.00",
                "exit_price": "103.50",
                "source_status": "开盘后可核验行情候选",
            },
        ]
        metrics = portfolio.current_rule_metrics(rows, -500)
        self.assertEqual(metrics["currentRuleClosedTrades"], 1)
        self.assertEqual(metrics["currentRuleWinRate"], "100.0%")
        self.assertEqual(metrics["currentRuleRealizedPnl"], "350.00")
        self.assertEqual(metrics["legacyCarryoverPnl"], "-850.00")

    def test_a_share_t_plus_one_quantity_is_frozen(self):
        self.assertEqual(sizing.available_quantity("A股", 200, "2026-07-13T10:00:00", "2026-07-13"), 0)
        self.assertEqual(sizing.available_quantity("A股", 200, "2026-07-12T10:00:00", "2026-07-13"), 200)

    def test_a_share_t_plus_one_blocks_same_day_exit(self):
        timestamp = datetime.now(execution.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now(execution.CHINA_TZ).date().isoformat()
        open_position = {
            "entry_price": "100.00",
            "take_profit": "104.00-105.00",
            "stop_loss": "97.00",
            "updated_at": f"{today}T09:30:00",
            "_entry_time": f"{today}T09:30:00",
        }
        row = execution.simulated_execution(
            self.pick,
            {"current_price": 96, "timestamp": timestamp},
            "盘中可核验行情候选",
            f"{today}T14:30:00",
            open_position=open_position,
        )
        self.assertEqual(row["exit_status"], "模拟持有")
        self.assertIn("T+1", row["risk_note"])

    def test_market_refresh_preserves_other_market(self):
        existing = {"records": [{"market": "美股", "symbol": "TEST", "asset_type": "stock"}]}
        fresh = [{"market": "A股", "symbol": "000001", "asset_type": "stock"}]
        merged = fetch.merge_records(existing, fresh, {"a_share"})
        self.assertEqual({row["market"] for row in merged}, {"A股", "美股"})

    def test_quick_health_check_uses_sample_size_as_expected_count(self):
        a_share = [{"symbol": str(index)} for index in range(30)]
        us_stock = [{"symbol": str(index)} for index in range(24)]
        benchmarks = [{"market": "A股"}, {"market": "美股"}]
        expected = fetch.expected_coverage(a_share, us_stock, benchmarks, us_limit=6)
        self.assertEqual(expected, {"a_share": 31, "us_stock": 6})
        self.assertEqual(fetch.minimum_coverage(expected)["us_stock"], 5)

    def test_historical_overallocation_is_not_negative_available_cash(self):
        available, gap, raw = portfolio.funding_state(230_000, 500)
        self.assertEqual(available, 0)
        self.assertEqual(gap, 129_500)
        self.assertEqual(raw, -129_500)

    def test_portfolio_uses_position_amounts_when_available(self):
        row = {"costAmountValue": 12_000, "marketValueValue": 12_600}
        self.assertEqual(portfolio.position_cost(row), 12_000)
        self.assertEqual(portfolio.position_value(row), 12_600)

    def test_legacy_positions_never_exceed_cash(self):
        rows = [
            {"market": "A股", "symbol": "EXPENSIVE", "entry_price": "1206.91", "_entry_time": "2026-07-01"},
            {"market": "美股", "symbol": "US", "entry_price": "390.49", "_entry_time": "2026-07-02"},
            {"market": "A股", "symbol": "AFFORDABLE", "entry_price": "80.00", "_entry_time": "2026-07-03"},
        ]
        funded, unfunded, remaining = normalizer.split_funded_positions(rows, capital=20_000)
        self.assertEqual([row["symbol"] for row in funded], ["US", "AFFORDABLE"])
        self.assertEqual([row["symbol"] for row in unfunded], ["EXPENSIVE"])
        used = 20_000 - remaining
        self.assertLessEqual(used, 20_000)

    def test_candidate_summary_deduplicates_fifteen_minute_observations(self):
        rows = [
            {"date": "2026-07-20", "time": "10:00:00", "market": "A股", "symbol": "000001", "asset_type": "stock"},
            {"date": "2026-07-20", "time": "10:15:00", "market": "A股", "symbol": "000001", "asset_type": "stock"},
            {"date": "2026-07-20", "time": "10:15:00", "market": "A股", "symbol": "000002", "asset_type": "stock"},
        ]
        deduped = performance.dedupe_daily_candidates(rows)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(next(row for row in deduped if row["symbol"] == "000001")["time"], "10:15:00")

    def test_overnight_backtest_requires_score_70(self):
        base = {"asset_type": "stock", "symbol": "TEST"}
        self.assertFalse(overnight.is_overnight_candidate({**base, "overnight_score": "69"}))
        self.assertTrue(overnight.is_overnight_candidate({**base, "overnight_score": "70"}))

    def test_overnight_drawdown_starts_from_initial_equity(self):
        self.assertAlmostEqual(overnight.max_drawdown([100.0, 99.17]), -0.83)

    def test_cloud_schedule_selects_a_share_session(self):
        now = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(cloud_schedule.active_markets(now), ["a_share"])

    def test_cloud_schedule_selects_us_session_with_dst(self):
        now = datetime(2026, 7, 21, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(cloud_schedule.active_markets(now), ["us_stock"])

    def test_cloud_schedule_skips_weekend(self):
        now = datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(cloud_schedule.active_markets(now), [])

    def test_cloud_schedule_keeps_intended_market_when_runner_is_late(self):
        late = datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(
            cloud_schedule.cycle_request(cloud_schedule.A_SHARE_CRON, late),
            ("a_share", "cycle"),
        )
        self.assertEqual(
            cloud_schedule.cycle_request(cloud_schedule.US_STOCK_CRON, late),
            ("us_stock", "cycle"),
        )

    def test_cloud_schedule_selects_daily_review(self):
        self.assertEqual(
            cloud_schedule.cycle_request("5 15 * * 1-5"),
            ("a_share", "review"),
        )

    def test_execution_performance_excludes_test_snapshot(self):
        rows = [
            {
                "updated_at": "2026-07-22T10:00:00",
                "market": "美股",
                "symbol": "TEST",
                "name": "测试",
                "action": "盘中：强势观察",
                "source_status": "行情源测试快照，不是实时推荐",
                "entry_status": "模拟买入",
                "entry_price": "100.00",
                "exit_status": "模拟持有",
            },
            {
                "updated_at": "2026-07-23T10:00:00",
                "market": "美股",
                "symbol": "TEST",
                "name": "测试",
                "action": "持仓跟踪",
                "source_status": "行情源测试快照，不是实时推荐",
                "entry_status": "已持仓",
                "entry_price": "100.00",
                "exit_status": "模拟止盈",
                "exit_price": "103.50",
            },
            {
                "updated_at": "2026-08-03T10:00:00",
                "market": "美股",
                "symbol": "LIVE",
                "name": "正式样本",
                "action": "盘中：强势观察",
                "source_status": "开盘后可核验行情候选",
                "entry_status": "模拟买入",
                "entry_price": "100.00",
                "exit_status": "模拟持有",
            },
            {
                "updated_at": "2026-08-05T10:00:00",
                "market": "美股",
                "symbol": "LIVE",
                "name": "正式样本",
                "action": "持仓跟踪",
                "source_status": "开盘后可核验行情候选",
                "entry_status": "已持仓",
                "entry_price": "100.00",
                "exit_status": "模拟止盈",
                "exit_price": "103.50",
            },
        ]
        stats = performance.execution_performance(rows, date(2026, 8, 8))
        self.assertEqual(stats["metrics"]["totalTrades"], 1)
        self.assertEqual(stats["metrics"]["totalWinRate"], "100.0%")
        self.assertEqual(stats["metrics"]["recentTrades"], 1)

    def test_wilson_interval_reflects_small_sample_uncertainty(self):
        low, high = performance.wilson_interval(5, 7)
        self.assertGreater(low, 35)
        self.assertLess(low, 37)
        self.assertGreater(high, 91)
        self.assertLess(high, 93)

    def test_strategy_diagnostics_holds_parameters_until_twenty_trades(self):
        current = [
            {"returnPct": value, "market": "美股"}
            for value in (3.5, 2.1, 1.8, 1.2, 0.9, -2.5, -1.7)
        ]
        candidates = [
            {
                "date": "2026-08-01",
                "action": "盘中：强势观察",
                "result_label": result,
            }
            for result in ("命中", "命中", "失败", "失败")
        ]
        diagnostics = performance.strategy_diagnostics(current, candidates)
        self.assertEqual(diagnostics["decision"], "保持参数")
        self.assertEqual(diagnostics["sampleTarget"], 20)
        self.assertEqual(diagnostics["remainingSamples"], 13)
        self.assertEqual(diagnostics["candidateWinRate"], "+50.00%")
        self.assertEqual(diagnostics["aShareClosedTrades"], 0)
        self.assertEqual(diagnostics["usStockClosedTrades"], 7)

    def test_cloud_close_schedule_forces_a_share_review(self):
        now = datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(cloud_schedule.cycle_request("5 15 * * 1-5", now), ("a_share", "review"))

    def test_cloud_close_schedule_forces_us_review(self):
        now = datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(cloud_schedule.cycle_request("5 16 * * 1-5", now), ("us_stock", "review"))

    def test_cloud_intraday_schedule_keeps_requested_market(self):
        now = datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)
        schedule = "2,17,32,47 9-11,13-15 * * 1-5"
        self.assertEqual(cloud_schedule.cycle_request(schedule, now), ("a_share", "cycle"))

    def test_review_uses_first_history_date_after_candidate(self):
        rows = [
            {"date": "2026-08-05", "close_price": "100"},
            {"date": "2026-08-06", "close_price": "103"},
            {"date": "2026-08-07", "close_price": "104"},
        ]
        quote = review.next_history_quote(rows, "2026-08-05")
        self.assertEqual(quote["raw_date"], "2026-08-06")
        self.assertEqual(quote["current_price"], "103")

    def test_review_price_history_reader_handles_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "price-history.csv"
            path.write_text("date,symbol,close_price\n2026-08-06,MSFT,103\n", encoding="utf-8")
            rows = review.read_csv(path)
        self.assertEqual(rows, [{"date": "2026-08-06", "symbol": "MSFT", "close_price": "103"}])

    def test_review_benchmark_matches_stock_review_date(self):
        rows = [
            {"date": "2026-08-05", "change_pct": "0.5"},
            {"date": "2026-08-06", "change_pct": "1.2"},
        ]
        quote = review.history_quote_on_date(rows, "2026-08-06")
        self.assertEqual(quote["change_pct"], "1.2")

    def test_review_deduplicates_intraday_candidate_observations(self):
        rows = [
            {"date": "2026-08-06", "time": "10:00:00", "market": "美股", "symbol": "MSFT"},
            {"date": "2026-08-06", "time": "10:15:00", "market": "美股", "symbol": "MSFT"},
            {"date": "2026-08-06", "time": "10:15:00", "market": "美股", "symbol": "AAPL"},
        ]
        deduped = review.latest_daily_candidates(rows)
        self.assertEqual(len(deduped), 2)
        msft = next(row for row in deduped if row["symbol"] == "MSFT")
        self.assertEqual(msft["time"], "10:15:00")

    def test_review_detail_panel_limits_large_backfill(self):
        reviewed = []
        result = {
            "execution_entry": "模拟买入",
            "execution_price": "100",
            "execution_exit": "模拟持有",
            "exit_price": "",
        }
        for index in range(25):
            reviewed.append(
                (
                    {
                        "symbol": f"S{index}",
                        "name": "测试",
                        "market": "美股",
                        "action": "盘中：强势观察",
                        "buy_zone": "99-101",
                        "stop_loss": "97",
                        "next_open": "100",
                        "next_close": "101",
                        "overnight_return": "+0.00%",
                        "intraday_return": "+1.00%",
                        "relative_return": "+0.50%",
                        "result_label": "命中",
                        "lesson": "测试",
                    },
                    result,
                )
            )
        rows = review.build_review_rows(reviewed, 0)
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0]["symbol"], "S5")

    def test_execution_performance_counts_one_closed_round_trip(self):
        rows = [
            {
                "updated_at": "2026-08-03T17:00:00",
                "market": "美股",
                "symbol": "MSFT",
                "entry_status": "模拟买入",
                "entry_price": "100",
                "exit_status": "模拟持有",
                "source_status": "开盘后可核验行情候选",
                "action": "盘中：强势观察",
            },
            {
                "updated_at": "2026-08-03T17:15:00",
                "market": "美股",
                "symbol": "MSFT",
                "entry_status": "已持仓",
                "entry_price": "100",
                "exit_status": "模拟持有",
                "source_status": "开盘后可核验行情候选",
            },
            {
                "updated_at": "2026-08-04T17:00:00",
                "market": "美股",
                "symbol": "MSFT",
                "entry_status": "已持仓",
                "entry_price": "100",
                "exit_status": "模拟止盈",
                "exit_price": "103.5",
                "source_status": "开盘后可核验行情候选",
            },
        ]
        trades = performance.closed_round_trips(rows)
        self.assertEqual(len(trades), 1)
        self.assertTrue(trades[0]["matchedEntry"])
        self.assertAlmostEqual(trades[0]["returnPct"], 3.5)

    def test_weekly_execution_metrics_preserve_buy_and_exit_events(self):
        rows = [
            {
                "updated_at": "2026-08-03T17:00:00",
                "market": "美股",
                "symbol": "MSFT",
                "entry_status": "模拟买入",
                "exit_status": "模拟持有",
                "source_status": "开盘后可核验行情候选",
            },
            {
                "updated_at": "2026-08-04T15:00:00",
                "market": "美股",
                "symbol": "MSFT",
                "entry_status": "已持仓",
                "exit_status": "模拟止盈",
                "source_status": "开盘后可核验行情候选",
            },
            {
                "updated_at": "2026-08-04T15:15:00",
                "market": "美股",
                "symbol": "MSFT",
                "entry_status": "等待触发",
                "exit_status": "未执行",
                "source_status": "开盘后可核验行情候选",
            },
        ]
        metrics = weekly.execution_metrics(rows, date(2026, 8, 2))
        self.assertEqual(metrics["executionBuys"], 1)
        self.assertEqual(metrics["executionExits"], 1)

    def test_a_share_entry_window_starts_at_ten(self):
        before = datetime(2026, 7, 21, 1, 45, tzinfo=timezone.utc)
        during = datetime(2026, 7, 21, 2, 15, tzinfo=timezone.utc)
        self.assertFalse(execution.entry_window_open("A股", before))
        self.assertTrue(execution.entry_window_open("A股", during))

    def test_us_entry_window_avoids_opening_volatility(self):
        before = datetime(2026, 7, 21, 13, 45, tzinfo=timezone.utc)
        during = datetime(2026, 7, 21, 14, 15, tzinfo=timezone.utc)
        self.assertFalse(execution.entry_window_open("美股", before))
        self.assertTrue(execution.entry_window_open("美股", during))

    def test_position_exits_after_five_trading_days(self):
        timestamp = datetime.now(execution.US_TZ).isoformat(timespec="seconds")
        open_position = {
            "entry_price": "100.00",
            "take_profit": "120.00-125.00",
            "stop_loss": "80.00",
            "updated_at": "2026-07-13T10:00:00",
            "_entry_time": "2026-07-13T10:00:00",
        }
        row = execution.simulated_execution(
            {**self.pick, "market": "美股"},
            {"current_price": 101, "timestamp": timestamp},
            "盘中可核验行情候选",
            "2026-07-20T14:00:00",
            open_position=open_position,
        )
        self.assertEqual(row["exit_status"], "模拟到期卖出")


if __name__ == "__main__":
    unittest.main()
