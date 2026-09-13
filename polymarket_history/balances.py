from dataclasses import dataclass
from decimal import Decimal

from eth_abi import decode, encode
from eth_utils import keccak

from .constants import COLLATERALS, CTF_ADDRESS
from .events import signed_amount
from .rpc import RpcPool
from .storage import Storage


@dataclass(frozen=True)
class BalanceComparison:
    symbol: str
    token_contract: str
    token_id: int | None
    calculated: int
    onchain: int

    @property
    def matches(self) -> bool:
        return self.calculated == self.onchain


def selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


async def compare_balances(
    rpc: RpcPool, storage: Storage, wallet: str, block: int
) -> list[BalanceComparison]:
    totals: dict[tuple[str, int | None], int] = {}
    for event in storage.events(wallet):
        token_id = int(event.token_id) if event.token_id is not None else None
        key = (event.token_contract, token_id)
        totals[key] = totals.get(key, 0) + signed_amount(event, wallet)

    comparisons: list[BalanceComparison] = []
    for collateral in COLLATERALS:
        data = selector("balanceOf(address)") + encode(["address"], [wallet])
        result = await rpc.eth_call(collateral.address, "0x" + data.hex(), block)
        onchain = decode(["uint256"], bytes.fromhex(result[2:]))[0]
        comparisons.append(
            BalanceComparison(
                collateral.symbol,
                collateral.address,
                None,
                totals.get((collateral.address, None), 0),
                int(onchain),
            )
        )

    token_ids = sorted(
        token_id
        for contract, token_id in totals
        if contract == CTF_ADDRESS and token_id is not None
    )
    for offset in range(0, len(token_ids), 100):
        batch = token_ids[offset : offset + 100]
        data = selector("balanceOfBatch(address[],uint256[])") + encode(
            ["address[]", "uint256[]"], [[wallet] * len(batch), batch]
        )
        result = await rpc.eth_call(CTF_ADDRESS, "0x" + data.hex(), block)
        onchain_values = decode(["uint256[]"], bytes.fromhex(result[2:]))[0]
        comparisons.extend(
            BalanceComparison(
                "CTF",
                CTF_ADDRESS,
                token_id,
                totals[(CTF_ADDRESS, token_id)],
                int(onchain),
            )
            for token_id, onchain in zip(batch, onchain_values)
        )
    return comparisons


def format_units(value: int, decimals: int = 6) -> str:
    return f"{Decimal(value) / Decimal(10**decimals):f}"
