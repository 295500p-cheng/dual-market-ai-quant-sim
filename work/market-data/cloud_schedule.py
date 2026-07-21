#!/usr/bin/env python3
import sys
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


CHINA_TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")


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


def main():
    active = active_markets()
    if not active:
        print("closed")
    elif len(active) == 2:
        print("both")
    else:
        print(active[0])


if __name__ == "__main__":
    sys.exit(main())

