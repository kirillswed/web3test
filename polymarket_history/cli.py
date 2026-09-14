import argparse
import asyncio
import json
import logging
from decimal import Decimal
from pathlib import Path

from polymarket import PolymarketError
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .polymarket_api import PolymarketAPI, normalize_address
from .storage import Storage
from .sync import WalletScanner


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Watch-only Polymarket API history collector")
    commands = root.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="download public Polymarket wallet data")
    sync.add_argument("address")
    sync.add_argument("--output", type=Path, help="save the full JSON report")

    report = commands.add_parser("report", help="report previously downloaded API data")
    report.add_argument("address")
    report.add_argument("--output", type=Path, help="save the full JSON report")
    return root


async def run(arguments: argparse.Namespace) -> int:
    settings = Settings.from_env()
    storage = Storage(settings.database_url)
    storage.create_schema()
    wallet = normalize_address(arguments.address)

    try:
        with storage.wallet_lock(wallet):
            if arguments.command == "sync":
                api = PolymarketAPI(
                    page_size=settings.api_page_size,
                    max_pages=settings.api_max_pages,
                )
                result = await WalletScanner(api, storage, settings).sync(wallet)
                print(
                    "Synced Polymarket API data: "
                    f"positions={result.positions}, activities={result.activities}, "
                    f"trades={result.trades}, markets={result.markets}, "
                    f"price_points={result.price_points}, status={result.status}"
                )
            document = build_report(storage.report(wallet))
            print_report(document)
            if arguments.output:
                arguments.output.parent.mkdir(parents=True, exist_ok=True)
                arguments.output.write_text(
                    json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                print(f"Report saved to {arguments.output}")
            return 0
    finally:
        storage.engine.dispose()


def build_report(data: dict) -> dict:
    open_positions = [item for item in data["positions"] if item.position_state == "open"]
    closed_positions = [item for item in data["positions"] if item.position_state == "closed"]
    open_value = sum((item.current_value for item in open_positions), Decimal(0))
    open_pnl = sum((item.cash_pnl for item in open_positions), Decimal(0))
    closed_pnl = sum((item.realized_pnl for item in closed_positions), Decimal(0))
    latest_prices: dict[str, object] = {}
    for point in data["prices"]:
        latest_prices[point.asset] = point
    return {
        "wallet": data["wallet"],
        "status": "PARTIAL",
        "source_status": data["status"],
        "coverage": data["coverage"],
        "completed_at": data["completed_at"].isoformat() if data["completed_at"] else None,
        "summary": {
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "activities": len(data["activities"]),
            "trades": len(data["trades"]),
            "markets": len(data["markets"]),
            "price_points": len(data["prices"]),
            "open_current_value": str(open_value),
            "open_cash_pnl": str(open_pnl),
            "closed_realized_pnl": str(closed_pnl),
            "estimated_total_pnl": str(open_pnl + closed_pnl),
            "pnl_status": "PARTIAL_API_ONLY",
        },
        "positions": [
            {
                "state": item.position_state,
                "asset": item.asset,
                "condition_id": item.condition_id,
                "title": item.title,
                "outcome": item.outcome,
                "size": str(item.size),
                "avg_price": str(item.avg_price),
                "current_value": str(item.current_value),
                "cash_pnl": str(item.cash_pnl),
                "realized_pnl": str(item.realized_pnl),
                "raw": item.raw,
            }
            for item in data["positions"]
        ],
        "activities": [item.raw for item in data["activities"]],
        "trades": [item.raw for item in data["trades"]],
        "markets": [
            {"condition_id": item.condition_id, "raw": item.raw}
            for item in data["markets"]
        ],
        "latest_prices": {
            asset: {
                "timestamp": point.timestamp,
                "price": str(point.price),
            }
            for asset, point in latest_prices.items()
        },
        "price_history": [
            {
                "asset": point.asset,
                "timestamp": point.timestamp,
                "price": str(point.price),
            }
            for point in data["prices"]
        ],
    }


def print_report(document: dict) -> None:
    summary = document["summary"]
    print(f"\nPolymarket API report for {document['wallet']} [{document['status']}]")
    print(
        f"positions: open={summary['open_positions']} closed={summary['closed_positions']} | "
        f"activities={summary['activities']} trades={summary['trades']} "
        f"markets={summary['markets']}"
    )
    print(
        f"value={summary['open_current_value']} | open_pnl={summary['open_cash_pnl']} | "
        f"closed_realized_pnl={summary['closed_realized_pnl']} | "
        f"estimated_total_pnl={summary['estimated_total_pnl']} "
        f"[{summary['pnl_status']}]"
    )
    print("Warning: public API data does not prove complete on-chain CTF history.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        return asyncio.run(run(parser().parse_args(argv)))
    except SQLAlchemyError:
        # SQL exceptions can include a DSN, credentials or a whole insert payload.
        print("error: PostgreSQL operation failed; check DATABASE_URL and database availability")
        return 1
    except (ValueError, RuntimeError, OSError, PolymarketError) as exc:
        print(f"error: {exc}")
        return 1
