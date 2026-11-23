"""pytest-asyncio-concurrent: N async tests in one group run concurrently on one loop.

Each request is its own test, so the invariant cannot be checked in any one of them; the
harness reads the database. There is no barrier: each test starts when the plugin schedules
it, after opening its own connection.

The natural way to write N tests is ``@pytest.mark.parametrize``, but with pytest 9.2.0 every
parametrized test in a group errors at teardown ("The fixture value for "i" is not available
during teardown") before sending anything (see ``results/wide/``). So the N tests are defined
one by one in a loop instead, which the plugin does run.
"""

import time

import httpx
import pytest
from _common import _SSL, CLIENTS, URL, note


def _make(i: int):  # type: ignore[no-untyped-def]
    @pytest.mark.asyncio_concurrent(group="race")
    async def test_reserve() -> None:
        async with httpx.AsyncClient(base_url=URL, timeout=30, verify=_SSL) as client:
            await client.get("/health")  # warm this test's connection
            started = time.perf_counter()
            response = await client.post("/events/1/reserve", json={"student": i})
            note(response.status_code, started)

    return test_reserve


for _i in range(CLIENTS):
    globals()[f"test_reserve_{_i:03d}"] = _make(_i)
