import logging
from dataclasses import dataclass

from .config import Settings
from .polymarket_api import PolymarketAPI, normalize_address
from .storage import Storage


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    status: str
    activities: int
    positions: int
    trades: int
    markets: int
    price_points: int


class WalletScanner:
    def __init__(
        self,
        api: PolymarketAPI,
        storage: Storage,
        settings: Settings,
    ) -> None:
        self.api = api
        self.storage = storage
        self.settings = settings

    async def sync(self, wallet: str) -> SyncResult:
        wallet = normalize_address(wallet)
        self.storage.mark_started(wallet)
        logger.info(
            "Synchronizing public Polymarket API data for watch-only wallet %s",
            wallet,
        )
        try:
            dataset = await self.api.collect_wallet(wallet)
            self.storage.save_dataset(wallet, dataset)
        except Exception as exc:
            self.storage.mark_failed(wallet, f"{type(exc).__name__}: {exc}")
            raise
        return SyncResult(
            status=dataset["status"],
            activities=len(dataset["activities"]),
            positions=len(dataset["positions"]),
            trades=len(dataset["trades"]),
            markets=len(dataset["markets"]),
            price_points=len(dataset["prices"]),
        )
