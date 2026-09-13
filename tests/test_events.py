from types import SimpleNamespace

import httpx
import pytest
from eth_abi import encode

from polymarket_history.constants import (
    COLLATERALS,
    CTF_ADDRESS,
    ERC1155_BATCH_TOPIC,
    ERC1155_SINGLE_TOPIC,
    ERC20_TRANSFER_TOPIC,
)
from polymarket_history.events import (
    address_topic,
    decode_wallet_log,
    normalize_address,
    signed_amount,
)
from polymarket_history.rpc import LogRangeTooLarge, RpcPool


WALLET = "0x46b353667fd7d846af3bbeda6584b0e5b883d3de"
OTHER = "0x1111111111111111111111111111111111111111"


def log(topic: str, topics: list[str], data: bytes, address: str) -> dict:
    return {
        "address": address,
        "topics": [topic, *topics],
        "data": "0x" + data.hex(),
        "blockNumber": "0x64",
        "blockHash": "0x" + "ab" * 32,
        "transactionHash": "0x" + "cd" * 32,
        "transactionIndex": "0x2",
        "logIndex": "0x3",
    }


def test_normalize_address() -> None:
    assert normalize_address(WALLET.upper().replace("0X", "0x")) == WALLET


def test_decode_erc20_transfer() -> None:
    raw = log(
        ERC20_TRANSFER_TOPIC,
        [address_topic(OTHER), address_topic(WALLET)],
        (1_500_000).to_bytes(32, "big"),
        COLLATERALS[0].address,
    )
    [event] = decode_wallet_log(raw, WALLET)
    assert event["token_standard"] == "ERC20"
    assert event["token_symbol"] == "USDC.e"
    assert int(event["amount"]) == 1_500_000
    assert event["to_address"] == WALLET


def test_decode_erc1155_single() -> None:
    raw = log(
        ERC1155_SINGLE_TOPIC,
        [address_topic(OTHER), address_topic(WALLET), address_topic(OTHER)],
        encode(["uint256", "uint256"], [123, 4_000_000]),
        CTF_ADDRESS,
    )
    [event] = decode_wallet_log(raw, WALLET)
    assert int(event["token_id"]) == 123
    assert int(event["amount"]) == 4_000_000
    assert event["from_address"] == WALLET


def test_decode_erc1155_batch_expands_rows() -> None:
    raw = log(
        ERC1155_BATCH_TOPIC,
        [address_topic(OTHER), address_topic(OTHER), address_topic(WALLET)],
        encode(["uint256[]", "uint256[]"], [[10, 20], [30, 40]]),
        CTF_ADDRESS,
    )
    events = decode_wallet_log(raw, WALLET)
    assert [(int(row["token_id"]), int(row["amount"])) for row in events] == [
        (10, 30),
        (20, 40),
    ]
    assert [row["sub_index"] for row in events] == [0, 1]


def test_signed_amount_handles_self_transfer() -> None:
    incoming = SimpleNamespace(from_address=OTHER, to_address=WALLET, amount=10)
    outgoing = SimpleNamespace(from_address=WALLET, to_address=OTHER, amount=10)
    self_transfer = SimpleNamespace(from_address=WALLET, to_address=WALLET, amount=10)
    assert signed_amount(incoming, WALLET) == 10
    assert signed_amount(outgoing, WALLET) == -10
    assert signed_amount(self_transfer, WALLET) == 0


def test_rpc_detects_explicit_block_range_limit() -> None:
    message = "{'code': -32602, 'message': 'range 49999 exceeds limit of 10000'}"
    assert RpcPool._is_range_error(message)
    assert RpcPool._range_limit(message) == 10_000


async def test_rpc_treats_get_logs_internal_error_as_splittable() -> None:
    rpc = RpcPool(("https://rpc.example",), concurrency=1, max_rps=100, timeout=1)

    async def fake_post(url: str, body: dict) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32603, "message": "Internal Server Error"},
            },
        )

    rpc._post = fake_post
    with pytest.raises(LogRangeTooLarge):
        await rpc.call("eth_getLogs", [{}])
    await rpc.client.aclose()
