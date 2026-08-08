#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


CHINA_TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")
A_SHARE_CRON = "2,17,32,47 9-11,13-15 * * 1-5"
US_STOCK_CRON = "2,17,32,47 9-16 * * 1-5"
A_SHARE_REVIEW_CRON = "5 15 * * 1-5"
US_STOCK_REVIEW_CRON = "5 16 * * 1-5"
CYCLE_SCHEDULES = {
    A_SHARE_CRON: ("a_share", "cycle"),
    US_STOCK_CRON: ("us_stock", "cycle"),
}
REVIEW_SCHEDULES = {
    A_SHARE_REVIEW_CRON: ("a_share", "review"),
    US_STOCK_REVIEW_CRON: ("us_stock", "review"),
}


def within(value, start, end):
    return start <= value <= end


def active_markets(now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    china = now.astimezone(CHINA_TZ)
    us = now.astimezone(US_TZ)
    active = []

    if china.weekday() < 5 and (
        within(china.time(), time(9, 25), time(11, 35))
        or within(china.time(), time(12, 55), time(15, 10))
    ):
        active.append("a_share")

    if us.weekday() < 5 and within(us.time(), time(9, 25), time(16, 10)):
        active.append("us_stock")

    return active


def cycle_request(schedule_expression="", now_utc=None):
    if schedule_expression in CYCLE_SCHEDULES:
        return CYCLE_SCHEDULES[schedule_expression]
    if schedule_expression in REVIEW_SCHEDULES:
        return REVIEW_SCHEDULES[schedule_expression]
    active = active_markets(now_utc)
    if not active:
        return "closed", "cycle"
    if len(active) == 2:
        return "both", "cycle"
    return active[0], "cycle"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", default="")
    args = parser.parse_args()
    market, mode = cycle_request(args.schedule)
    print(f"{market} {mode}")


if __name__ == "__main__":
    sys.exit(main())
