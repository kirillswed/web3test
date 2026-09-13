from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WalletEvent(Base):
    __tablename__ = "wallet_events"
    __table_args__ = (
        UniqueConstraint(
            "chain_id",
            "wallet_address",
            "transaction_hash",
            "log_index",
            "sub_index",
            name="uq_wallet_event_log",
        ),
        Index("ix_wallet_events_wallet_block", "wallet_address", "block_number"),
        Index("ix_wallet_events_wallet_asset", "wallet_address", "token_contract"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    token_contract: Mapped[str] = mapped_column(String(42), nullable=False)
    token_symbol: Mapped[str | None] = mapped_column(String(32))
    token_standard: Mapped[str] = mapped_column(String(8), nullable=False)
    token_id: Mapped[Decimal | None] = mapped_column(Numeric(78, 0))
    from_address: Mapped[str] = mapped_column(String(42), nullable=False)
    to_address: Mapped[str] = mapped_column(String(42), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    transaction_index: Mapped[int] = mapped_column(Integer, nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sub_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    __table_args__ = (
        UniqueConstraint("chain_id", "wallet_address", name="uq_sync_cursor_wallet"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    last_scanned_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
