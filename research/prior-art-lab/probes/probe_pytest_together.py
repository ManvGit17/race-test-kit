"""pytest-together: ``together(*callables)`` releases them from a barrier and measures spread.

By default (strict) a spread wider than 5 ms raises NotConcurrent. The probe calls it with
``strict=False`` only so it can record the spread first, then applies the same rule itself,
so the verdict is the one the default would give.
"""

from functools import partial

import pytest
from _common import CLIENTS, SEATS, extra, post, warm_clients


def test_no_oversell(together) -> None:  # type: ignore[no-untyped-def]
    clients = warm_clients()
    result = together(*[partial(post, clients[i], i) for i in range(CLIENTS)], strict=False)
    extra(together_spread_ms=result.spread_ms, together_overlapped=result.overlapped)
    if not result.overlapped:
        pytest.fail(f"NotConcurrent: workers started {result.spread_ms:.1f}ms apart")
    result.raise_for_errors()
    assert result.count(lambda status: status == 201) <= SEATS
