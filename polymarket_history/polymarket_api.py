import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Any, Awaitable, Callable

from polymarket import PolymarketClient


logger = logging.getLogger(__name__)


def normalize_address(value: str) -> str:
    value = value.lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"Invalid Ethereum address: {value}")
    int(value[2:], 16)
    return value


def _raw(model: Any) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, dict):
        return model
    raise TypeError(f"Unsupported Polymarket model: {type(model).__name__}")


def _record_key(raw: dict) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode()).hexdigest()


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


@dataclass(frozen=True)
class PageResult:
    rows: list[Any]
    pages: int
    complete: bool


class PolymarketAPI:
    def __init__(
        self,
        *,
        page_size: int = 100,
        max_pages: int = 10_000,
        client_factory: Callable[[], PolymarketClient] = PolymarketClient,
    ) -> None:
        self.page_size = page_size
        self.max_pages = max_pages
        self.client_factory = client_factory

    async def collect_wallet(self, wallet: str) -> dict:
        wallet = normalize_address(wallet)
        started_at = datetime.now(timezone.utc)
        async with self.client_factory() as client:
            open_positions = await self._paginate(
                lambda offset: client.get_address_positions(
                    wallet,
                    limit=self.page_size,
                    offset=offset,
                    size_threshold=0.0,
                    strict_parse=True,
                ),
                "open positions",
            )
            closed_positions = await self._paginate(
                lambda offset: client.get_closed_positions(
                    wallet,
                    limit=self.page_size,
                    offset=offset,
                    sort_by="TIMESTAMP",
                    sort_direction="ASC",
                    strict_parse=True,
                ),
                "closed positions",
            )
            activities = await self._collect_activity(client, wallet)
            trades, trade_coverage = await self._collect_trades(client, wallet)

            condition_ids = {
                str(row.condition_id)
                for row in (
                    open_positions.rows + closed_positions.rows + activities.rows + trades
                )
                if getattr(row, "condition_id", None)
            }
            assets = {
                str(row.asset)
                for row in (
                    open_positions.rows + closed_positions.rows + activities.rows + trades
                )
                if getattr(row, "asset", None)
            }
            markets, market_errors = await self._collect_markets(client, condition_ids)
            prices, price_coverage = await self._collect_prices(client, assets)

        api_complete = all((
            open_positions.complete,
            closed_positions.complete,
            activities.complete,
            trade_coverage["complete"],
            not market_errors,
            price_coverage["complete"],
        ))
        coverage = {
            "source": "Polymarket public Gamma/CLOB/Data APIs",
            "api_complete": api_complete,
            "onchain_complete": False,
            "open_position_pages": open_positions.pages,
            "closed_position_pages": closed_positions.pages,
            "activity_pages": activities.pages,
            "activity_complete": activities.complete,
            "activity_unique_records": len(activities.rows),
            "trade": trade_coverage,
            "prices": price_coverage,
            "market_errors": market_errors,
            "note": "API-only watch mode cannot prove complete ERC-1155 transfer history",
        }
        return {
            "started_at": started_at,
            "status": "partial",
            "coverage": coverage,
            "positions": self._position_rows(
                wallet, open_positions.rows, closed_positions.rows
            ),
            "activities": self._activity_rows(wallet, activities.rows),
            "trades": self._trade_rows(wallet, trades),
            "markets": markets,
            "prices": prices,
        }

    async def _paginate(
        self,
        fetch_page: Callable[[int], Awaitable[list[Any]]],
        label: str,
    ) -> PageResult:
        rows: list[Any] = []
        seen_pages: set[str] = set()
        seen_rows: set[str] = set()
        for page in range(self.max_pages):
            batch = await fetch_page(page * self.page_size)
            if not isinstance(batch, list):
                raise TypeError(f"{label} endpoint did not return a list")
            raw_batch = [_raw(item) for item in batch]
            page_key = _record_key({"rows": raw_batch})
            if batch and page_key in seen_pages:
                logger.warning(
                    "Polymarket API source=%s repeated page at offset=%s; "
                    "stopping with incomplete coverage",
                    label,
                    page * self.page_size,
                )
                return PageResult(rows, page + 1, False)
            seen_pages.add(page_key)
            for item, raw in zip(batch, raw_batch):
                row_key = _record_key(raw)
                if row_key not in seen_rows:
                    rows.append(item)
                    seen_rows.add(row_key)
            logger.info(
                "Polymarket API source=%s page=%s rows=%s total=%s",
                label,
                page + 1,
                len(batch),
                len(rows),
            )
            if len(batch) < self.page_size:
                return PageResult(rows, page + 1, True)
        logger.warning(
            "Polymarket API source=%s reached API_MAX_PAGES=%s; coverage is incomplete",
            label,
            self.max_pages,
        )
        return PageResult(rows, self.max_pages, False)

    async def _collect_trades(self, client, wallet: str) -> tuple[list[Any], dict]:
        rows: list[Any] = []
        evidence: list[dict] = []
        for page in range(self.max_pages):
            result = await client.get_market_trades_result_v1(
                user=wallet,
                limit=self.page_size,
                offset=page * self.page_size,
            )
            raw = _raw(result)
            evidence.append({
                "status": _enum_value(result.status),
                "parse_complete": result.parse_complete,
                "source_complete": result.source_complete,
                "coverage": raw["coverage"],
                "request": raw["request"],
                "error": result.error,
            })
            if _enum_value(result.status) == "error":
                return rows, {"complete": False, "pages": page + 1, "evidence": evidence}
            rows.extend(result.trades)
            logger.info(
                "Polymarket API source=trades page=%s rows=%s total=%s status=%s",
                page + 1,
                len(result.trades),
                len(rows),
                _enum_value(result.status),
            )
            if len(result.trades) < self.page_size:
                complete = bool(result.parse_complete and result.source_complete is not False)
                return rows, {
                    "complete": complete,
                    "pages": page + 1,
                    "evidence": evidence,
                }
        return rows, {
            "complete": False,
            "pages": self.max_pages,
            "evidence": evidence,
            "error": "API_MAX_PAGES reached",
        }

    async def _collect_activity(self, client, wallet: str) -> PageResult:
        """Exhaust activity with time windows because the API caps offset at 5000."""
        upper = int(datetime.now(timezone.utc).timestamp())
        windows = [(0, upper)]
        rows: dict[str, Any] = {}
        pages = 0
        complete = True

        while windows:
            start, end = windows.pop()
            window_rows: list[Any] = []
            reached_offset_cap = True
            offset = 0
            while offset < 5000:
                if pages >= self.max_pages:
                    logger.warning(
                        "Polymarket API source=activity reached API_MAX_PAGES=%s",
                        self.max_pages,
                    )
                    return PageResult(list(rows.values()), pages, False)
                batch = await client.get_address_activity(
                    wallet,
                    limit=self.page_size,
                    offset=offset,
                    start=start,
                    end=end,
                    sort_by="TIMESTAMP",
                    strict_parse=True,
                    retry=True,
                )
                if not isinstance(batch, list):
                    raise TypeError("activity endpoint did not return a list")
                pages += 1
                window_rows.extend(batch)
                for item in batch:
                    raw = _raw(item)
                    rows.setdefault(_record_key(raw), item)
                logger.info(
                    "Polymarket API source=activity window=%s..%s offset=%s "
                    "rows=%s unique_total=%s",
                    start,
                    end,
                    offset,
                    len(batch),
                    len(rows),
                )
                if len(batch) < self.page_size:
                    reached_offset_cap = False
                    break
                offset += self.page_size

            if not reached_offset_cap:
                continue
            if start >= end:
                logger.warning(
                    "Activity has at least 5000 records at timestamp=%s; "
                    "the public API cannot enumerate that second completely",
                    start,
                )
                complete = False
                continue

            timestamps = [int(item.timestamp) for item in window_rows]
            observed_min = min(timestamps)
            observed_max = max(timestamps)
            if observed_min < observed_max:
                split = (observed_min + observed_max) // 2
            else:
                split = (start + end) // 2
            split = max(start, min(split, end - 1))
            logger.warning(
                "Activity window=%s..%s reached offset cap; splitting at %s",
                start,
                end,
                split,
            )
            windows.append((split + 1, end))
            windows.append((start, split))

        ordered = sorted(rows.values(), key=lambda item: int(item.timestamp))
        return PageResult(ordered, pages, complete)

    async def _collect_markets(
        self, client, condition_ids: set[str]
    ) -> tuple[list[dict], list[dict]]:
        rows: list[dict] = []
        errors: list[dict] = []
        for condition_id in sorted(condition_ids):
            try:
                market = await client.get_market_by_condition(condition_id)
                rows.append({"condition_id": condition_id, "raw": _raw(market)})
            except Exception as exc:
                errors.append({"condition_id": condition_id, "error": str(exc)})
        return rows, errors

    async def _collect_prices(
        self, client, assets: set[str]
    ) -> tuple[list[dict], dict]:
        rows: list[dict] = []
        evidence: dict[str, dict] = {}
        complete = True
        for asset in sorted(assets):
            try:
                result = await client.get_prices_history_result_v1(asset, interval="max")
                raw = _raw(result)
                asset_complete = (
                    _enum_value(result.status) != "error"
                    and result.parse_complete
                    and result.range_complete is not False
                )
                complete = complete and asset_complete
                evidence[asset] = {
                    "status": _enum_value(result.status),
                    "parse_complete": result.parse_complete,
                    "range_complete": result.range_complete,
                    "coverage": raw["coverage"],
                    "request": raw["request"],
                    "error": result.error,
                }
                rows.extend(
                    {"asset": asset, "timestamp": point.timestamp, "price": point.price}
                    for point in result.points
                )
            except Exception as exc:
                complete = False
                evidence[asset] = {"status": "error", "error": str(exc)}
        return rows, {"complete": complete, "assets": evidence}

    @staticmethod
    def _position_rows(wallet: str, open_rows: list[Any], closed_rows: list[Any]) -> list[dict]:
        rows = []
        for item in open_rows:
            raw = _raw(item)
            rows.append({
                "wallet_address": wallet,
                "position_state": "open",
                "asset": item.asset,
                "condition_id": item.condition_id,
                "title": item.title,
                "outcome": item.outcome,
                "size": item.size,
                "avg_price": item.avg_price,
                "current_value": item.current_value,
                "cash_pnl": item.cash_pnl,
                "realized_pnl": item.realized_pnl,
                "raw": raw,
            })
        for item in closed_rows:
            raw = _raw(item)
            rows.append({
                "wallet_address": wallet,
                "position_state": "closed",
                "asset": item.asset,
                "condition_id": item.condition_id,
                "title": item.title,
                "outcome": item.outcome,
                "size": Decimal(0),
                "avg_price": item.avg_price,
                "current_value": Decimal(0),
                "cash_pnl": item.realized_pnl,
                "realized_pnl": item.realized_pnl,
                "raw": raw,
            })
        return rows

    @staticmethod
    def _activity_rows(wallet: str, items: list[Any]) -> list[dict]:
        rows = []
        for item in items:
            raw = _raw(item)
            rows.append({
                "wallet_address": wallet,
                "record_key": _record_key(raw),
                "timestamp": item.timestamp,
                "activity_type": _enum_value(item.type),
                "transaction_hash": item.transaction_hash.lower(),
                "asset": item.asset,
                "condition_id": item.condition_id,
                "side": _enum_value(item.side),
                "size": item.size,
                "usdc_size": item.usdc_size,
                "price": item.price,
                "raw": raw,
            })
        return rows

    @staticmethod
    def _trade_rows(wallet: str, items: list[Any]) -> list[dict]:
        rows = []
        for item in items:
            raw = _raw(item)
            rows.append({
                "wallet_address": wallet,
                "record_key": _record_key(raw),
                "timestamp": item.timestamp,
                "transaction_hash": item.transaction_hash.lower(),
                "asset": item.asset,
                "condition_id": item.condition_id,
                "side": _enum_value(item.side),
                "size": item.size,
                "price": item.price,
                "raw": raw,
            })
        return rows
