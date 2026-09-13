import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    rpc_urls: tuple[str, ...]
    database_url: str
    start_block: int = 7_530_000
    log_chunk_blocks: int = 50_000
    rpc_concurrency: int = 8
    rpc_max_rps: float = 20
    confirmations: int = 64
    rpc_timeout_seconds: float = 30

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        raw_urls = os.getenv("POLYGON_RPC_URLS") or os.getenv("POLYGON_RPC_URL", "")
        urls = tuple(url.strip() for url in raw_urls.split(",") if url.strip())
        if not urls:
            raise ValueError("POLYGON_RPC_URLS is required")
        if any("FIRST_POLYGON_RPC" in url or "SECOND_POLYGON_RPC" in url for url in urls):
            raise ValueError("Replace placeholder values in POLYGON_RPC_URLS")

        database_url = os.getenv("DATABASE_URL", "")
        if not database_url:
            raise ValueError("DATABASE_URL is required")

        return cls(
            rpc_urls=urls,
            database_url=database_url,
            start_block=int(os.getenv("START_BLOCK", "7530000")),
            log_chunk_blocks=max(1, int(os.getenv("LOG_CHUNK_BLOCKS", "50000"))),
            rpc_concurrency=max(1, int(os.getenv("RPC_CONCURRENCY", "8"))),
            rpc_max_rps=max(0.1, float(os.getenv("RPC_MAX_RPS", "20"))),
            confirmations=max(0, int(os.getenv("CONFIRMATIONS", "64"))),
            rpc_timeout_seconds=max(
                1, float(os.getenv("RPC_TIMEOUT_SECONDS", "30"))
            ),
        )
