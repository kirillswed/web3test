from collections.abc import Iterable

from sqlalchemy import create_engine, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from .constants import CHAIN_ID
from .models import Base, SyncCursor, WalletEvent


class Storage:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def cursor(self, wallet: str) -> int | None:
        with self.sessions() as session:
            return session.scalar(
                select(SyncCursor.last_scanned_block).where(
                    SyncCursor.chain_id == CHAIN_ID,
                    SyncCursor.wallet_address == wallet,
                )
            )

    def rewind(self, wallet: str, from_block: int) -> None:
        with self.sessions.begin() as session:
            session.execute(
                delete(WalletEvent).where(
                    WalletEvent.chain_id == CHAIN_ID,
                    WalletEvent.wallet_address == wallet,
                    WalletEvent.block_number >= from_block,
                )
            )
            self._upsert_cursor(session, wallet, from_block - 1)

    def save_chunk(
        self, wallet: str, events: Iterable[dict[str, object]], last_block: int
    ) -> int:
        rows = list(events)
        with self.sessions.begin() as session:
            if rows:
                statement = insert(WalletEvent).values(rows)
                session.execute(
                    statement.on_conflict_do_nothing(
                        constraint="uq_wallet_event_log"
                    )
                )
            self._upsert_cursor(session, wallet, last_block)
        return len(rows)

    def events(self, wallet: str) -> list[WalletEvent]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(WalletEvent)
                    .where(
                        WalletEvent.chain_id == CHAIN_ID,
                        WalletEvent.wallet_address == wallet,
                    )
                    .order_by(
                        WalletEvent.block_number,
                        WalletEvent.transaction_index,
                        WalletEvent.log_index,
                        WalletEvent.sub_index,
                    )
                )
            )

    @staticmethod
    def _upsert_cursor(session: Session, wallet: str, block: int) -> None:
        statement = insert(SyncCursor).values(
            chain_id=CHAIN_ID,
            wallet_address=wallet,
            last_scanned_block=block,
        )
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_sync_cursor_wallet",
                set_={"last_scanned_block": block},
            )
        )
