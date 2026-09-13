import logging
import time
from dataclasses import dataclass

from .config import Settings
from .constants import CHAIN_ID
from .events import decode_wallet_log, fetch_wallet_logs, normalize_address
from .rpc import RpcError, RpcPool
from .storage import Storage


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    start_block: int
    end_block: int
    events_seen: int


class WalletScanner:
    def __init__(self, rpc: RpcPool, storage: Storage, settings: Settings) -> None:
        self.rpc = rpc
        self.storage = storage
        self.settings = settings

    async def sync(
        self, wallet: str, from_block: int | None = None
    ) -> SyncResult:
        wallet = normalize_address(wallet)
        if await self.rpc.chain_id() != CHAIN_ID:
            raise RuntimeError("RPC endpoint is not Polygon mainnet (chain ID 137)")

        target = await self.rpc.finalized_block_number(self.settings.confirmations)
        cursor = self.storage.cursor(wallet)
        if from_block is not None:
            if from_block < 0:
                raise ValueError("--from-block cannot be negative")
            if cursor is not None and from_block > cursor + 1:
                raise ValueError(
                    "--from-block is above the cursor and would create a history gap"
                )
            self.storage.rewind(wallet, from_block)
            start = from_block
        elif cursor is not None:
            start = cursor + 1
        else:
            start = await self._initial_block(wallet, target)

        if start > target:
            logger.info("Wallet %s is already synchronized through block %s", wallet, target)
            return SyncResult(start, target, 0)

        logger.info(
            "Synchronizing wallet %s from block %s through finalized block %s",
            wallet,
            start,
            target,
        )
        total_events = 0
        started_at = time.monotonic()
        current = start
        while current <= target:
            end = min(target, current + self.settings.log_chunk_blocks - 1)
            logger.info("Fetching Polymarket logs for blocks %s..%s", current, end)
            logs = await fetch_wallet_logs(self.rpc, wallet, current, end)
            rows = [
                row
                for log in logs
                for row in decode_wallet_log(log, wallet)
            ]
            total_events += self.storage.save_chunk(wallet, rows, end)
            self._print_progress(start, target, end, total_events, started_at)
            current = end + 1
        return SyncResult(start, target, total_events)

    async def _initial_block(self, wallet: str, target: int) -> int:
        start = min(self.settings.start_block, target)
        try:
            if await self.rpc.get_code(wallet, target) in ("0x", "0x0"):
                return start
            if await self.rpc.get_code(wallet, start) not in ("0x", "0x0"):
                return start
            low, high = start, target
            while low < high:
                middle = (low + high) // 2
                if await self.rpc.get_code(wallet, middle) in ("0x", "0x0"):
                    low = middle + 1
                else:
                    high = middle
            return low
        except RpcError:
            return start

    @staticmethod
    def _print_progress(
        start: int, target: int, current: int, events: int, started_at: float
    ) -> None:
        scanned = current - start + 1
        total = target - start + 1
        elapsed = max(time.monotonic() - started_at, 0.001)
        blocks_per_second = scanned / elapsed
        remaining = (total - scanned) / blocks_per_second
        percentage = 100 * scanned / total
        logger.info(
            "Progress: block %s/%s | %6.2f%% | events %s | %s blocks/s | ETA %s",
            current,
            target,
            percentage,
            f"{events:,}",
            f"{blocks_per_second:,.0f}",
            format_duration(remaining),
        )


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
