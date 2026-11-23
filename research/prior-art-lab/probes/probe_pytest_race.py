"""pytest-race: the ``start_race`` fixture runs one target in N threads behind a barrier."""

from _common import CLIENTS, SEATS, post, warm_clients


def test_no_oversell(start_race) -> None:  # type: ignore[no-untyped-def]
    clients = warm_clients()
    statuses: list[int] = []

    def target(i: int) -> None:
        statuses.append(post(clients[i], i))

    start_race(threads_num=CLIENTS, target=target, thread_args={"i": list(range(CLIENTS))})
    assert statuses.count(201) <= SEATS
