from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from .models import (
    ApiActivity,
    ApiMarket,
    ApiPosition,
    ApiPricePoint,
    ApiSyncRun,
    ApiTrade,
    Base,
)


class Storage:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def wallet_lock(self, wallet: str):
        key = int.from_bytes(sha256(f"polymarket-api:{wallet}".encode()).digest()[:8],
                             "big", signed=True)
        with self.engine.connect() as connection:
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            connection.commit()
            if not acquired:
                raise RuntimeError("Another sync/report is using this wallet; retry after it finishes")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()

    def mark_started(self, wallet: str) -> None:
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.execute(
                insert(ApiSyncRun)
                .values(
                    wallet_address=wallet,
                    status="running",
                    coverage={},
                    error=None,
                    started_at=now,
                    completed_at=None,
                )
                .on_conflict_do_update(
                    index_elements=[ApiSyncRun.wallet_address],
                    set_={
                        "status": "running",
                        "coverage": {},
                        "error": None,
                        "started_at": now,
                        "completed_at": None,
                        "updated_at": now,
                    },
                )
            )

    def mark_failed(self, wallet: str, error: str) -> None:
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.execute(
                insert(ApiSyncRun)
                .values(
                    wallet_address=wallet,
                    status="failed",
                    coverage={},
                    error=error[:4000],
                    started_at=now,
                    completed_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[ApiSyncRun.wallet_address],
                    set_={
                        "status": "failed",
                        "error": error[:4000],
                        "completed_at": now,
                        "updated_at": now,
                    },
                )
            )

    def save_dataset(self, wallet: str, dataset: dict) -> None:
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.execute(delete(ApiPosition).where(ApiPosition.wallet_address == wallet))
            self._insert_batches(session, ApiPosition, dataset["positions"])
            self._insert_ignore(session, ApiActivity, dataset["activities"], "uq_api_activity")
            self._insert_ignore(session, ApiTrade, dataset["trades"], "uq_api_trade")
            self._upsert_markets(session, dataset["markets"])
            self._upsert_prices(session, dataset["prices"])
            session.execute(
                insert(ApiSyncRun)
                .values(
                    wallet_address=wallet,
                    status=dataset["status"],
                    coverage=dataset["coverage"],
                    error=None,
                    started_at=dataset["started_at"],
                    completed_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[ApiSyncRun.wallet_address],
                    set_={
                        "status": dataset["status"],
                        "coverage": dataset["coverage"],
                        "error": None,
                        "completed_at": now,
                        "updated_at": now,
                    },
                )
            )

    def report(self, wallet: str) -> dict:
        with self.sessions() as session:
            run = session.get(ApiSyncRun, wallet)
            if run is None:
                raise RuntimeError("Wallet has not been synchronized")
            positions = list(session.scalars(
                select(ApiPosition)
                .where(ApiPosition.wallet_address == wallet)
                .order_by(ApiPosition.position_state, ApiPosition.title, ApiPosition.asset)
            ))
            activities = list(session.scalars(
                select(ApiActivity)
                .where(ApiActivity.wallet_address == wallet)
                .order_by(ApiActivity.timestamp)
            ))
            trades = list(session.scalars(
                select(ApiTrade)
                .where(ApiTrade.wallet_address == wallet)
                .order_by(ApiTrade.timestamp)
            ))
            condition_ids = {
                item.condition_id for item in positions + activities + trades
                if item.condition_id
            }
            assets = {
                item.asset for item in positions + activities + trades
                if item.asset
            }
            markets = (
                list(session.scalars(
                    select(ApiMarket).where(ApiMarket.condition_id.in_(condition_ids))
                ))
                if condition_ids else []
            )
            prices = (
                list(session.scalars(
                    select(ApiPricePoint)
                    .where(ApiPricePoint.asset.in_(assets))
                    .order_by(ApiPricePoint.asset, ApiPricePoint.timestamp)
                ))
                if assets else []
            )
            return {
                "wallet": wallet,
                "status": run.status,
                "coverage": run.coverage,
                "completed_at": run.completed_at,
                "positions": positions,
                "activities": activities,
                "trades": trades,
                "markets": markets,
                "prices": prices,
            }

    @staticmethod
    def _insert_batches(session, model, rows: list[dict]) -> None:
        for offset in range(0, len(rows), 500):
            session.execute(insert(model).values(rows[offset:offset + 500]))

    @classmethod
    def _insert_ignore(cls, session, model, rows: list[dict], constraint: str) -> None:
        for offset in range(0, len(rows), 500):
            statement = insert(model).values(rows[offset:offset + 500])
            session.execute(statement.on_conflict_do_nothing(constraint=constraint))

    @staticmethod
    def _upsert_markets(session, rows: list[dict]) -> None:
        for row in rows:
            statement = insert(ApiMarket).values(row)
            session.execute(statement.on_conflict_do_update(
                index_elements=[ApiMarket.condition_id],
                set_={"raw": statement.excluded.raw, "updated_at": datetime.now(timezone.utc)},
            ))

    @staticmethod
    def _upsert_prices(session, rows: list[dict]) -> None:
        for offset in range(0, len(rows), 500):
            statement = insert(ApiPricePoint).values(rows[offset:offset + 500])
            session.execute(statement.on_conflict_do_update(
                constraint="uq_api_price_point",
                set_={"price": statement.excluded.price},
            ))
