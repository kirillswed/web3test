import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from polymarket_history.models import (
    ApiActivity,
    ApiPosition,
    ApiPricePoint,
    ApiSyncRun,
    ApiTrade,
)
from polymarket_history.storage import Storage


WALLET = "0x" + "22" * 20


@pytest.fixture
def storage():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run isolated PostgreSQL integration tests")
    schema = "web3test_api_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    instance = Storage(make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        instance.create_schema()
        yield instance
    finally:
        instance.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def dataset():
    condition = "0x" + "11" * 32
    tx_hash = "0x" + "aa" * 32
    return {
        "started_at": datetime.now(timezone.utc),
        "status": "partial",
        "coverage": {"api_complete": True, "onchain_complete": False},
        "positions": [{
            "wallet_address": WALLET, "position_state": "open", "asset": "123",
            "condition_id": condition, "title": "Market", "outcome": "Yes",
            "size": Decimal("2"), "avg_price": Decimal(".4"),
            "current_value": Decimal("1"), "cash_pnl": Decimal(".2"),
            "realized_pnl": Decimal("0"), "raw": {"asset": "123"},
        }],
        "activities": [{
            "wallet_address": WALLET, "record_key": "a" * 64, "timestamp": 1,
            "activity_type": "TRADE", "transaction_hash": tx_hash, "asset": "123",
            "condition_id": condition, "side": "BUY", "size": Decimal("2"),
            "usdc_size": Decimal(".8"), "price": Decimal(".4"), "raw": {"type": "TRADE"},
        }],
        "trades": [{
            "wallet_address": WALLET, "record_key": "b" * 64, "timestamp": 1,
            "transaction_hash": tx_hash, "asset": "123", "condition_id": condition,
            "side": "BUY", "size": Decimal("2"), "price": Decimal(".4"),
            "raw": {"side": "BUY"},
        }],
        "markets": [{"condition_id": condition, "raw": {"question": "Market"}}],
        "prices": [{"asset": "123", "timestamp": 1, "price": Decimal(".5")}],
    }


def test_save_dataset_is_idempotent_and_replaces_position_snapshot(storage):
    storage.mark_started(WALLET)
    storage.save_dataset(WALLET, dataset())
    storage.save_dataset(WALLET, dataset())

    with storage.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ApiPosition)) == 1
        assert session.scalar(select(func.count()).select_from(ApiActivity)) == 1
        assert session.scalar(select(func.count()).select_from(ApiTrade)) == 1
        assert session.scalar(select(func.count()).select_from(ApiPricePoint)) == 1
        assert session.get(ApiSyncRun, WALLET).status == "partial"

    report = storage.report(WALLET)
    assert len(report["positions"]) == 1
    assert len(report["markets"]) == 1
    assert len(report["prices"]) == 1


def test_failed_sync_records_error_without_dataset(storage):
    storage.mark_started(WALLET)
    storage.mark_failed(WALLET, "broken")
    with storage.sessions() as session:
        run = session.get(ApiSyncRun, WALLET)
        assert run.status == "failed"
        assert run.error == "broken"
