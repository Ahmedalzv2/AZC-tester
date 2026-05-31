"""Thin Alpaca paper-trading client used by the rebalance runner.

Hard paper-guard: the client refuses to act unless it's talking to the paper
endpoint AND the account carries the paper `PA` prefix. Even if live keys were
pasted into .env by mistake, this raises instead of trading real money. Dry-run
is the default; submitting requires it to be turned off explicitly.
"""
from __future__ import annotations

import os
import pathlib

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"


def assert_paper(account_number: str, base_url: str) -> None:
    """Belt-and-suspenders: paper accounts start with 'PA' and live on the paper
    endpoint. Raises if either signals a live account."""
    if not str(account_number).startswith("PA"):
        raise RuntimeError(
            f"refusing to trade: account {account_number!r} lacks the paper 'PA' prefix")
    if "paper" not in str(base_url).lower():
        raise RuntimeError(
            f"refusing to trade: endpoint {base_url!r} is not the paper endpoint")


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith("ALPACA_") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip())


class AlpacaPaper:
    def __init__(self, dry_run: bool = True):
        _load_env()
        key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY missing from env/.env")
        self.dry_run = dry_run
        self.client = TradingClient(key, secret, paper=True)
        acct = self.client.get_account()
        assert_paper(str(acct.account_number), str(self.client._base_url))  # guard
        self._equity = float(acct.equity)

    def equity(self) -> float:
        return self._equity

    def positions(self) -> dict[str, float]:
        """symbol -> current market value in USD."""
        return {p.symbol: float(p.market_value) for p in self.client.get_all_positions()}

    def submit(self, order: dict) -> str:
        """Execute one abstract order from rebalance.plan_orders. Returns a short
        status string. Dry-run logs the intent and submits nothing."""
        sym, action = order["symbol"], order["action"]
        if self.dry_run:
            detail = "close" if action == "close" else f"{action} ${order['notional']:,.2f}"
            return f"DRY {sym} {detail}"
        if action == "close":
            self.client.close_position(sym)
            return f"closed {sym}"
        side = OrderSide.BUY if action == "buy" else OrderSide.SELL
        req = MarketOrderRequest(symbol=sym, notional=order["notional"],
                                 side=side, time_in_force=TimeInForce.DAY)
        res = self.client.submit_order(order_data=req)
        return f"{action} {sym} ${order['notional']:,.2f} -> {res.id}"
