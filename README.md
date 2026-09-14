# Polymarket watch-only history

This project downloads public wallet data through
[`PolymarketClient`](https://github.com/perpetual-s/polymarket-python-infrastructure):

- current and closed positions;
- public activity and wallet trades;
- referenced market metadata;
- token price history and latest prices;
- API-provided realized and unrealized PnL fields.

Data is stored idempotently in PostgreSQL. No wallet private key is required.

## Important limitation

Polymarket public APIs are not an on-chain archive. The report therefore uses
`PARTIAL` / `PARTIAL_API_ONLY` status and does not claim complete ERC-1155
transfer history or on-chain reconciliation.

## Setup

Use a virtual environment because the client library has strict Pydantic
requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
docker compose up -d --wait
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Environment variables:

- `DATABASE_URL` — PostgreSQL SQLAlchemy DSN.
- `API_PAGE_SIZE` — Data API page size, default `100`.
- `API_MAX_PAGES` — safety limit per paginated source, default `200`.
- `POLYMARKET_*` — optional settings supported by the installed client.

## Commands

Download and persist all supported public data:

```powershell
python -m polymarket_history sync 0x46b353667fd7d846af3bbeda6584b0e5b883d3de --output reports/wallet.json
```

Build a report from PostgreSQL without network requests:

```powershell
python -m polymarket_history report 0x46b353667fd7d846af3bbeda6584b0e5b883d3de --output reports/wallet.json
```

The sync operation is atomic: pagination or strict parsing failures do not
replace the last successfully stored snapshot. Activities, trades and price
points use stable conflict keys, so repeated syncs are idempotent.

## Tests

```powershell
python -m pytest -q
```

PostgreSQL integration tests are optional:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@localhost:5432/polymarket_history'
python -m pytest -q
Remove-Item Env:TEST_DATABASE_URL
```
