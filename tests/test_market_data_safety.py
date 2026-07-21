import importlib.util
import sys
import unittest
from datetime import datetime
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
