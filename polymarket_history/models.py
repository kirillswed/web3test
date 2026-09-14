from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ApiActivity(Base):
    __tablename__ = "api_activities"
    __table_args__ = (
        UniqueConstraint("wallet_address", "record_key", name="uq_api_activity"),
        Index("ix_api_activity_wallet_time", "wallet_address", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    record_key: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    asset: Mapped[str | None] = mapped_column(String(78))
    condition_id: Mapped[str | None] = mapped_column(String(66))
    side: Mapped[str | None] = mapped_column(String(8))
    size: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False)
    usdc_size: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(78, 18))
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ApiPosition(Base):
    __tablename__ = "api_positions"
    __table_args__ = (
        UniqueConstraint(
            "wallet_address", "position_state", "asset", name="uq_api_position"
        ),
        Index("ix_api_position_wallet_state", "wallet_address", "position_state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    position_state: Mapped[str] = mapped_column(String(8), nullable=False)
    asset: Mapped[str] = mapped_column(String(78), nullable=False)
    condition_id: Mapped[str] = mapped_column(String(66), nullable=False)
    title: Mapped[str | None] = mapped_column(String)
    outcome: Mapped[str | None] = mapped_column(String)
    size: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False, default=0)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False, default=0)
    current_value: Mapped[Decimal] = mapped_column(
        Numeric(78, 18), nullable=False, default=0
    )
    cash_pnl: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False, default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(78, 18), nullable=False, default=0
    )
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ApiTrade(Base):
    __tablename__ = "api_trades"
    __table_args__ = (
        UniqueConstraint("wallet_address", "record_key", name="uq_api_trade"),
        Index("ix_api_trade_wallet_time", "wallet_address", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    record_key: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    asset: Mapped[str] = mapped_column(String(78), nullable=False)
    condition_id: Mapped[str] = mapped_column(String(66), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ApiMarket(Base):
    __tablename__ = "api_markets"

    condition_id: Mapped[str] = mapped_column(String(66), primary_key=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApiPricePoint(Base):
    __tablename__ = "api_price_points"
    __table_args__ = (
        UniqueConstraint("asset", "timestamp", name="uq_api_price_point"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(78), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(78, 18), nullable=False)


class ApiSyncRun(Base):
    __tablename__ = "api_sync_runs"

    wallet_address: Mapped[str] = mapped_column(String(42), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    coverage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
