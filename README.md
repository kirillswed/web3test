# Minimal Polygon wallet scanner

This service reads Polymarket collateral transfers (USDC.e, USDC, and pUSD)
and CTF position transfers directly from Polygon RPC, stores them in
PostgreSQL, and verifies the reconstructed balances with
`balanceOf`/`balanceOfBatch`. It does not use the Polymarket API or a
third-party indexer.

The scanner validates Polygon mainnet chain ID `137` and synchronizes through
the standard `finalized` block tag when the RPC supports it. Polygon considers
finalized blocks irreversible. `CONFIRMATIONS` is used as a fallback.

## Prerequisites

- Python 3.12 or newer
- Docker Desktop
- One or more Polygon mainnet RPC URLs

## Install Docker

### Windows

1. Enable hardware virtualization in BIOS/UEFI.
2. Install
   [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
3. During installation, use the WSL 2 backend when offered.
4. Start Docker Desktop and wait until the engine is running.
5. Verify the installation in PowerShell:

```powershell
docker --version
docker compose version
```

Docker installation guides for macOS and Linux are available in the
[official Docker documentation](https://docs.docker.com/engine/install/).

## Setup

Run these commands from the project directory in PowerShell:

```powershell
python -m pip install -e ".[test]"
docker compose up -d --wait
Copy-Item .env.example .env
```

Open `.env` and replace `POLYGON_RPC_URLS` with your Polygon mainnet RPC
endpoints. Multiple endpoints must be comma-separated.

## Run the scanner

```powershell
python -m polymarket_history sync 0x46b353667fd7d846af3bbeda6584b0e5b883d3de
```

The command logs the wallet, finalized block range, current RPC request range,
automatically detected `eth_getLogs` limits, progress, decoded event count,
speed, and ETA. RPC ranges that exceed a provider limit are split
automatically. The cursor is committed after each completed chunk, so running
the same command again resumes the scan.

After synchronization, print and verify the stored balances:

```powershell
python -m polymarket_history report 0x46b353667fd7d846af3bbeda6584b0e5b883d3de
```

The `wallet_events` and `sync_cursors` tables are created automatically.
Use `--from-block N` to rebuild history from an earlier block. The requested
block must not be higher than the saved cursor.

For a smart-contract wallet, the first scan uses `eth_getCode` and binary
search to find its deployment block. For an EOA, or when historical
`eth_getCode` is unavailable, scanning starts at `START_BLOCK`.

## Environment variables

- `POLYGON_RPC_URLS` — comma-separated Polygon mainnet RPC endpoints. Requests
  are distributed across the pool. Endpoints that return rate-limit, network,
  or server errors are temporarily put on cooldown. The legacy singular
  `POLYGON_RPC_URL` is also supported.
- `DATABASE_URL` — PostgreSQL SQLAlchemy DSN.
- `START_BLOCK` — earliest block to scan. Defaults to `7530000`, before the
  Polymarket CTF deployment on Polygon.
- `LOG_CHUNK_BLOCKS` — initial `eth_getLogs` range. Defaults to `50000`.
  Provider-specific range errors are detected and requests are split.
- `RPC_CONCURRENCY` — maximum concurrent HTTP requests. Defaults to `8`.
- `RPC_MAX_RPS` — global request rate across the RPC pool. Defaults to `20`.
- `CONFIRMATIONS` — blocks excluded when the RPC does not support `finalized`.
- `RPC_TIMEOUT_SECONDS` — timeout for one RPC request.

Do not set `START_BLOCK` later than the wallet's first relevant transfer if
you need an exact replay. Amounts are stored as raw integers; floating-point
numbers are never used.

## Limitations

Only the exact supplied address is analyzed. A related proxy or Safe address
is not discovered automatically. The scanner stores transfers for known
Polymarket collateral contracts and CTF positions only. Other ERC-20,
ERC-721, or ERC-1155 assets are not indexed. Market names and `OrderFilled`
events are intentionally omitted because they are not required to reconstruct
balances.

## Reset the local database

Warning: this permanently deletes the local PostgreSQL data volume.

```powershell
docker compose down -v
docker compose up -d --wait
```
