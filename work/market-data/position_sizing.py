#!/usr/bin/env python3
import math


TARGET_POSITION_NOTIONAL = 10_000.0
A_SHARE_LOT_SIZE = 100


def simulated_quantity(market, entry_price, target_notional=TARGET_POSITION_NOTIONAL):
    """Return a whole-share simulated quantity using each market's lot rules."""
    if entry_price is None or entry_price <= 0 or target_notional <= 0:
        return 0
    if market == "A股":
        lots = math.floor(target_notional / (entry_price * A_SHARE_LOT_SIZE))
        return max(1, lots) * A_SHARE_LOT_SIZE
    return max(1, math.floor(target_notional / entry_price))


def simulated_cost(market, entry_price, target_notional=TARGET_POSITION_NOTIONAL):
    return simulated_quantity(market, entry_price, target_notional) * (entry_price or 0)


def entry_order_quantity(market, entry_price, target_notional=TARGET_POSITION_NOTIONAL):
    """Return a quantity for a new order without exceeding its notional cap."""
    quantity = simulated_quantity(market, entry_price, target_notional)
    if quantity and quantity * entry_price > target_notional:
        return 0
    return quantity


def entry_order_cost(market, entry_price, target_notional=TARGET_POSITION_NOTIONAL):
    return entry_order_quantity(market, entry_price, target_notional) * (entry_price or 0)


def available_quantity(market, quantity, entry_time, current_date):
    if market == "A股" and str(entry_time or "")[:10] == str(current_date or "")[:10]:
        return 0
    return quantity
