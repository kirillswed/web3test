from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from polymarket_history.cli import build_report
from polymarket_history.config import Settings
from polymarket_history.polymarket_api import PolymarketAPI, normalize_address
from polymarket_history.sync import WalletScanner


WALLET = "0x46b353667fd7d846af3bbeda6584b0e5b883d3de"


class Item(SimpleNamespace):
    def model_dump(self, mode="json"):
        def convert(value):
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, list):
                return [convert(item) for item in value]
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            return getattr(value, "value", value)

        return {key: convert(value) for key, value in vars(self).items()}


def position():
    return Item(
        asset="123",
        condition_id="0x" + "11" * 32,
        title="Will it work?",
        outcome="Yes",
        size=Decimal("5"),
        avg_price=Decimal("0.4"),
        current_value=Decimal("3"),
        cash_pnl=Decimal("1"),
        realized_pnl=Decimal("0.2"),
    )


def closed_position():
    return Item(
        asset="456",
        condition_id="0x" + "22" * 32,
        title="Closed market",
        outcome="No",
        avg_price=Decimal("0.7"),
        total_bought=Decimal("2"),
        realized_pnl=Decimal("-0.5"),
    )


def activity():
    return Item(
        timestamp=100,
        type="TRADE",
        transaction_hash="0x" + "aa" * 32,
        size=Decimal("5"),
        usdc_size=Decimal("2"),
        asset="123",
        condition_id="0x" + "11" * 32,
        side="BUY",
        price=Decimal("0.4"),
    )


def trade():
    return Item(
        timestamp=100,
        transaction_hash="0x" + "aa" * 32,
        asset="123",
        condition_id="0x" + "11" * 32,
        side="BUY",
        size=Decimal("5"),
        price=Decimal("0.4"),
    )


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_address_positions(self, _wallet, *, offset, **_):
        return [position()] if offset == 0 else []

    async def get_closed_positions(self, _wallet, *, offset, **_):
        return [closed_position()] if offset == 0 else []

    async def get_address_activity(self, _wallet, *, offset, **_):
        return [activity()] if offset == 0 else []

    async def get_market_trades_result_v1(self, *, offset, **_):
        rows = [trade()] if offset == 0 else []
        return Item(
            status="success",
            parse_complete=True,
            source_complete=True,
            trades=rows,
            coverage={"first_page": offset == 0, "page_full": bool(rows)},
            request={"attempt_count": 1},
            error=None,
        )

    async def get_market_by_condition(self, condition_id):
        return {"condition_id": condition_id, "question": "Market"}

    async def get_prices_history_result_v1(self, asset, interval):
        assert interval == "max"
        return Item(
            status="success",
            parse_complete=True,
            range_complete=True,
            points=[Item(timestamp=100, price=Decimal("0.6"))],
            coverage={"explicit_range": False},
            request={"attempt_count": 1},
            error=None,
        )


async def test_collect_wallet_paginates_and_preserves_decimal_values():
    api = PolymarketAPI(page_size=1, max_pages=10, client_factory=FakeClient)
    dataset = await api.collect_wallet(WALLET)

    assert len(dataset["positions"]) == 2
    assert len(dataset["activities"]) == 1
    assert len(dataset["trades"]) == 1
    assert len(dataset["markets"]) == 2
    assert len(dataset["prices"]) == 2
    assert dataset["positions"][0]["cash_pnl"] == Decimal("1")
    assert dataset["coverage"]["api_complete"] is True
    assert dataset["coverage"]["onchain_complete"] is False
    assert dataset["status"] == "partial"


async def test_page_limit_marks_result_incomplete():
    api = PolymarketAPI(page_size=1, max_pages=1, client_factory=FakeClient)
    dataset = await api.collect_wallet(WALLET)
    assert dataset["coverage"]["api_complete"] is False
    assert dataset["coverage"]["open_position_pages"] == 1


async def test_scanner_marks_failures_without_saving_partial_dataset():
    api = Mock()
    api.collect_wallet = AsyncMock(side_effect=RuntimeError("broken page"))
    storage = Mock()
    scanner = WalletScanner(api, storage, Settings(database_url="unused"))

    with pytest.raises(RuntimeError, match="broken page"):
        await scanner.sync(WALLET)

    storage.mark_started.assert_called_once_with(WALLET)
    storage.mark_failed.assert_called_once()
    storage.save_dataset.assert_not_called()


def test_report_uses_api_pnl_and_marks_it_partial():
    data = {
        "wallet": WALLET,
        "status": "partial",
        "coverage": {"onchain_complete": False},
        "completed_at": None,
        "positions": [
            SimpleNamespace(
                position_state="open", asset="1", condition_id="c1", title="Open",
                outcome="Yes", size=Decimal("2"), avg_price=Decimal(".2"),
                current_value=Decimal("1"), cash_pnl=Decimal(".6"),
                realized_pnl=Decimal("0"), raw={},
            ),
            SimpleNamespace(
                position_state="closed", asset="2", condition_id="c2", title="Closed",
                outcome="No", size=Decimal("0"), avg_price=Decimal(".4"),
                current_value=Decimal("0"), cash_pnl=Decimal("-.1"),
                realized_pnl=Decimal("-.1"), raw={},
            ),
        ],
        "activities": [],
        "trades": [],
        "markets": [],
        "prices": [],
    }
    report = build_report(data)
    assert report["summary"]["estimated_total_pnl"] == "0.5"
    assert report["summary"]["pnl_status"] == "PARTIAL_API_ONLY"
    assert report["status"] == "PARTIAL"


def test_normalize_address():
    assert normalize_address(WALLET.upper().replace("0X", "0x")) == WALLET
