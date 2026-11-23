"""No plugin: the ThreadPoolExecutor most blog posts hand-roll, with no barrier."""

from concurrent.futures import ThreadPoolExecutor

from _common import CLIENTS, SEATS, post, warm_clients


def test_no_oversell() -> None:
    clients = warm_clients()
    with ThreadPoolExecutor(CLIENTS) as pool:
        statuses = list(pool.map(post, clients, range(CLIENTS)))
    assert statuses.count(201) <= SEATS
