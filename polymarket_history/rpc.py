import asyncio
import itertools
import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx


logger = logging.getLogger(__name__)


class RpcError(RuntimeError):
    pass


class LogRangeTooLarge(RpcError):
    pass


class RpcPool:
    def __init__(
        self,
        urls: tuple[str, ...],
        *,
        concurrency: int,
        max_rps: float,
        timeout: float,
    ) -> None:
        self.urls = urls
        self.client = httpx.AsyncClient(timeout=timeout)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.rate_lock = asyncio.Lock()
        self.next_request_at = 0.0
        self.request_interval = 1.0 / max_rps
        self.cooldown_until = {url: 0.0 for url in urls}
        self.counter = itertools.count(1)
        self.cursor = 0
        self.max_log_blocks: int | None = None

    async def __aenter__(self) -> "RpcPool":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    async def call(self, method: str, params: list[Any]) -> Any:
        failures: list[str] = []
        for _round in range(4):
            for _ in range(len(self.urls)):
                url = await self._next_url()
                try:
                    response = await self._post(
                        url,
                        {
                            "jsonrpc": "2.0",
                            "id": next(self.counter),
                            "method": method,
                            "params": params,
                        },
                    )
                    payload = response.json()
                    if error := payload.get("error"):
                        message = str(error)
                        code = error.get("code") if isinstance(error, dict) else None
                        if method == "eth_getLogs" and (
                            self._is_range_error(message) or code == -32603
                        ):
                            raise LogRangeTooLarge(message)
                        if self._is_transient(message):
                            raise httpx.HTTPStatusError(
                                message, request=response.request, response=response
                            )
                        raise RpcError(f"{method}: {message}")
                    return payload["result"]
                except LogRangeTooLarge:
                    raise
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    failures.append(f"{self._host(url)}: {exc}")
                    self.cooldown_until[url] = time.monotonic() + 30
            await asyncio.sleep(1)
        raise RpcError(f"{method} failed on every RPC provider: {'; '.join(failures[-4:])}")

    async def get_logs(
        self, address: str | list[str], topics: list[Any], start: int, end: int
    ) -> list[dict[str, Any]]:
        if self.max_log_blocks and end - start + 1 > self.max_log_blocks:
            ranges = [
                (first, min(first + self.max_log_blocks - 1, end))
                for first in range(start, end + 1, self.max_log_blocks)
            ]
            batches = await asyncio.gather(
                *(
                    self.get_logs(address, topics, first, last)
                    for first, last in ranges
                )
            )
            return [log for batch in batches for log in batch]
        try:
            return await self.call(
                "eth_getLogs",
                [
                    {
                        "address": address,
                        "topics": topics,
                        "fromBlock": hex(start),
                        "toBlock": hex(end),
                    }
                ],
            )
        except LogRangeTooLarge as exc:
            if start >= end:
                raise
            detected_limit = self._range_limit(str(exc))
            if detected_limit and (
                self.max_log_blocks is None
                or detected_limit < self.max_log_blocks
            ):
                self.max_log_blocks = detected_limit
                logger.info(
                    "RPC limits eth_getLogs to %s blocks; splitting requests",
                    detected_limit,
                )
                return await self.get_logs(address, topics, start, end)
            middle = (start + end) // 2
            logger.warning(
                "RPC could not serve eth_getLogs for blocks %s..%s; "
                "retrying as %s..%s and %s..%s",
                start,
                end,
                start,
                middle,
                middle + 1,
                end,
            )
            left, right = await asyncio.gather(
                self.get_logs(address, topics, start, middle),
                self.get_logs(address, topics, middle + 1, end),
            )
            return left + right

    async def finalized_block_number(self, confirmations: int) -> int:
        try:
            block = await self.call("eth_getBlockByNumber", ["finalized", False])
            if block:
                return int(block["number"], 16)
        except RpcError:
            pass
        latest = int(await self.call("eth_blockNumber", []), 16)
        return max(0, latest - confirmations)

    async def chain_id(self) -> int:
        return int(await self.call("eth_chainId", []), 16)

    async def get_code(self, address: str, block: int | str) -> str:
        tag = hex(block) if isinstance(block, int) else block
        return await self.call("eth_getCode", [address, tag])

    async def eth_call(self, to: str, data: str, block: int | str) -> str:
        tag = hex(block) if isinstance(block, int) else block
        return await self.call("eth_call", [{"to": to, "data": data}, tag])

    async def _post(self, url: str, body: dict[str, Any]) -> httpx.Response:
        async with self.semaphore:
            async with self.rate_lock:
                delay = self.next_request_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                self.next_request_at = time.monotonic() + self.request_interval
            response = await self.client.post(url, json=body)
            response.raise_for_status()
            return response

    async def _next_url(self) -> str:
        while True:
            now = time.monotonic()
            for _ in range(len(self.urls)):
                url = self.urls[self.cursor % len(self.urls)]
                self.cursor += 1
                if self.cooldown_until[url] <= now:
                    return url
            await asyncio.sleep(max(0.1, min(self.cooldown_until.values()) - now))

    @staticmethod
    def _host(url: str) -> str:
        return urlsplit(url).netloc

    @staticmethod
    def _is_transient(message: str) -> bool:
        text = message.lower()
        return any(
            marker in text
            for marker in (
                "rate limit",
                "too many requests",
                "timeout",
                "temporarily unavailable",
                "internal error",
            )
        )

    @staticmethod
    def _is_range_error(message: str) -> bool:
        text = message.lower()
        return any(
            marker in text
            for marker in (
                "block range",
                "response size",
                "too many results",
                "query returned more than",
                "limit exceeded",
                "exceeds limit",
            )
        )

    @staticmethod
    def _range_limit(message: str) -> int | None:
        match = re.search(r"(?:limit(?:ed)?(?:\s+to|\s+of)?)[^\d]*(\d+)", message, re.I)
        if not match:
            return None
        return max(1, int(match.group(1)))
