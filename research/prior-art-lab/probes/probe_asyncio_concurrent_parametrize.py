"""pytest-asyncio-concurrent written the natural way, with ``@pytest.mark.parametrize``.

Kept to reproduce a finding: with pytest 9.2.0 every test in the group errors at teardown
("The fixture value for "i" is not available during teardown") and no request is sent.
``probe_asyncio_concurrent.py`` is the working variant.
"""

import time

import httpx
import pytest
from _common import _SSL, CLIENTS, URL, note


@pytest.mark.asyncio_concurrent(group="race")
@pytest.mark.parametrize("i", range(CLIENTS))
async def test_reserve(i: int) -> None:
    async with httpx.AsyncClient(base_url=URL, timeout=30, verify=_SSL) as client:
        await client.get("/health")
        started = time.perf_counter()
        response = await client.post("/events/1/reserve", json={"student": i})
        note(response.status_code, started)
