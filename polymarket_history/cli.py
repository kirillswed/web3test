import argparse
import asyncio
import logging

from .balances import compare_balances, format_units
from .config import Settings
from .constants import CTF_ADDRESS
from .events import normalize_address
from .rpc import RpcPool
from .storage import Storage
from .sync import WalletScanner


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Polygon Polymarket wallet scanner")
    commands = root.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="scan finalized Polygon logs")
    sync.add_argument("address")
    sync.add_argument("--from-block", type=int)

    report = commands.add_parser("report", help="compare replayed and on-chain balances")
    report.add_argument("address")
    return root


async def run(arguments: argparse.Namespace) -> int:
    settings = Settings.from_env()
    storage = Storage(settings.database_url)
    storage.create_schema()
    wallet = normalize_address(arguments.address)

    async with RpcPool(
        settings.rpc_urls,
        concurrency=settings.rpc_concurrency,
        max_rps=settings.rpc_max_rps,
        timeout=settings.rpc_timeout_seconds,
    ) as rpc:
        if arguments.command == "sync":
            result = await WalletScanner(rpc, storage, settings).sync(
                wallet, arguments.from_block
            )
            print(
                f"Synced blocks {result.start_block}..{result.end_block}; "
                f"decoded rows: {result.events_seen}"
            )
            block = result.end_block
        else:
            block = storage.cursor(wallet)
            if block is None:
                raise RuntimeError("Wallet has not been synchronized yet")

        comparisons = await compare_balances(rpc, storage, wallet, block)
        mismatches = print_report(comparisons, block)
        return 2 if mismatches else 0


def print_report(comparisons: list, block: int) -> int:
    print(f"\nBalance replay at finalized block {block}:")
    mismatches = 0
    for item in comparisons:
        if item.token_contract == CTF_ADDRESS:
            calculated = format_units(item.calculated)
            onchain = format_units(item.onchain)
            label = f"CTF #{item.token_id}"
        else:
            calculated = format_units(item.calculated)
            onchain = format_units(item.onchain)
            label = item.symbol
        status = "OK" if item.matches else "MISMATCH"
        mismatches += not item.matches
        print(f"  {label}: calculated={calculated} onchain={onchain} [{status}]")
    return int(mismatches)


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
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1
