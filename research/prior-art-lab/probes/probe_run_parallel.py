"""pytest-run-parallel: the same test body runs in N threads, released by a barrier.

Each thread runs its own copy of the test, so no single test sees all N responses: the
"at most SEATS reservations" check cannot be written inside the test. The probe therefore
only sends; the harness reads the database to see whether the race happened.
"""

import pytest
from _common import CLIENTS, post, warm_clients

CLIENT_POOL = warm_clients()


@pytest.mark.force_parallel_threads(CLIENTS)
def test_reserve(thread_index: int) -> None:
    post(CLIENT_POOL[thread_index], thread_index)
