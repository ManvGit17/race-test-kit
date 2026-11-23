"""No plugin: threads parked on a threading.Barrier, then released together.

This is the reference for what a barrier start alone buys over the plain thread pool.
"""

import threading

from _common import CLIENTS, SEATS, post, warm_clients


def test_no_oversell() -> None:
    clients = warm_clients()
    gate = threading.Barrier(CLIENTS)
    statuses: list[int] = []

    def worker(i: int) -> None:
        gate.wait()
        statuses.append(post(clients[i], i))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(CLIENTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses.count(201) <= SEATS
