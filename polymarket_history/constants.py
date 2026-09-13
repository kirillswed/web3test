from dataclasses import dataclass

from eth_utils import keccak


CHAIN_ID = 137
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
CTF_ADDRESS = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"


@dataclass(frozen=True)
class Collateral:
    symbol: str
    address: str
    decimals: int = 6


COLLATERALS = (
    Collateral("USDC.e", "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"),
    Collateral("USDC", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"),
    Collateral("pUSD", "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"),
)
COLLATERAL_BY_ADDRESS = {item.address: item for item in COLLATERALS}


def event_topic(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


ERC20_TRANSFER_TOPIC = event_topic("Transfer(address,address,uint256)")
ERC1155_SINGLE_TOPIC = event_topic(
    "TransferSingle(address,address,address,uint256,uint256)"
)
ERC1155_BATCH_TOPIC = event_topic(
    "TransferBatch(address,address,address,uint256[],uint256[])"
)
