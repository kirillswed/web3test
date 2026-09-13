import asyncio
from decimal import Decimal
from typing import Any

from eth_abi import decode

from .constants import (
    CHAIN_ID,
    COLLATERAL_BY_ADDRESS,
    COLLATERALS,
    CTF_ADDRESS,
    ERC1155_BATCH_TOPIC,
    ERC1155_SINGLE_TOPIC,
    ERC20_TRANSFER_TOPIC,
)
from .rpc import RpcPool


def normalize_address(value: str) -> str:
    value = value.lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"Invalid Ethereum address: {value}")
    int(value[2:], 16)
    return value


def address_topic(address: str) -> str:
    return "0x" + ("0" * 24) + normalize_address(address)[2:]


def topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


async def fetch_wallet_logs(
    rpc: RpcPool, wallet: str, start: int, end: int
) -> list[dict[str, Any]]:
    wallet_filter = address_topic(wallet)
    collateral_addresses = [item.address for item in COLLATERALS]
    queries = (
        rpc.get_logs(
            collateral_addresses,
            [ERC20_TRANSFER_TOPIC, wallet_filter],
            start,
            end,
        ),
        rpc.get_logs(
            collateral_addresses,
            [ERC20_TRANSFER_TOPIC, None, wallet_filter],
            start,
            end,
        ),
        rpc.get_logs(
            CTF_ADDRESS,
            [ERC1155_SINGLE_TOPIC, None, wallet_filter],
            start,
            end,
        ),
        rpc.get_logs(
            CTF_ADDRESS,
            [ERC1155_SINGLE_TOPIC, None, None, wallet_filter],
            start,
            end,
        ),
        rpc.get_logs(
            CTF_ADDRESS,
            [ERC1155_BATCH_TOPIC, None, wallet_filter],
            start,
            end,
        ),
        rpc.get_logs(
            CTF_ADDRESS,
            [ERC1155_BATCH_TOPIC, None, None, wallet_filter],
            start,
            end,
        ),
    )
    batches = await asyncio.gather(*queries)
    unique: dict[tuple[str, int], dict[str, Any]] = {}
    for log in (item for batch in batches for item in batch):
        unique[(log["transactionHash"].lower(), int(log["logIndex"], 16))] = log
    return sorted(
        unique.values(),
        key=lambda item: (
            int(item["blockNumber"], 16),
            int(item["transactionIndex"], 16),
            int(item["logIndex"], 16),
        ),
    )


def decode_wallet_log(log: dict[str, Any], wallet: str) -> list[dict[str, object]]:
    wallet = normalize_address(wallet)
    topic0 = log["topics"][0].lower()
    contract = normalize_address(log["address"])

    if topic0 == ERC20_TRANSFER_TOPIC:
        source = topic_address(log["topics"][1])
        destination = topic_address(log["topics"][2])
        amounts = [(None, int(log["data"], 16))]
        standard = "ERC20"
        symbol = COLLATERAL_BY_ADDRESS[contract].symbol
    elif topic0 == ERC1155_SINGLE_TOPIC:
        source = topic_address(log["topics"][2])
        destination = topic_address(log["topics"][3])
        token_id, amount = decode(
            ["uint256", "uint256"], bytes.fromhex(log["data"][2:])
        )
        amounts = [(int(token_id), int(amount))]
        standard = "ERC1155"
        symbol = "CTF"
    elif topic0 == ERC1155_BATCH_TOPIC:
        source = topic_address(log["topics"][2])
        destination = topic_address(log["topics"][3])
        token_ids, values = decode(
            ["uint256[]", "uint256[]"], bytes.fromhex(log["data"][2:])
        )
        if len(token_ids) != len(values):
            raise ValueError("Malformed TransferBatch: ids and values differ in length")
        amounts = [(int(token_id), int(amount)) for token_id, amount in zip(token_ids, values)]
        standard = "ERC1155"
        symbol = "CTF"
    else:
        raise ValueError(f"Unsupported event topic: {topic0}")

    if source != wallet and destination != wallet:
        return []

    common = {
        "chain_id": CHAIN_ID,
        "wallet_address": wallet,
        "token_contract": contract,
        "token_symbol": symbol,
        "token_standard": standard,
        "from_address": source,
        "to_address": destination,
        "block_number": int(log["blockNumber"], 16),
        "block_hash": log["blockHash"].lower(),
        "transaction_hash": log["transactionHash"].lower(),
        "transaction_index": int(log["transactionIndex"], 16),
        "log_index": int(log["logIndex"], 16),
    }
    return [
        {
            **common,
            "token_id": Decimal(token_id) if token_id is not None else None,
            "amount": Decimal(amount),
            "sub_index": sub_index,
        }
        for sub_index, (token_id, amount) in enumerate(amounts)
    ]


def signed_amount(event: Any, wallet: str) -> int:
    wallet = normalize_address(wallet)
    if event.from_address == wallet and event.to_address == wallet:
        return 0
    amount = int(event.amount)
    return amount if event.to_address == wallet else -amount
