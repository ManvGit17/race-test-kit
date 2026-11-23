"""Hypothesis stateful testing: a state machine whose rule reserves a seat over HTTP.

Rules run one after another, so requests never overlap. This shows what the most capable
sequential tool finds against the same bug.
"""

import httpx
from _common import CLIENTS, SEATS, URL, note
from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

client = httpx.Client(base_url=URL, timeout=30)


class Shop(RuleBasedStateMachine):
    @initialize()
    def reset(self) -> None:
        client.post("/admin/reset", params={"capacity": SEATS})
        self.held = 0

    @rule(student=st.integers(min_value=0, max_value=10_000))
    def reserve(self, student: int) -> None:
        response = client.post("/events/1/reserve", json={"student": student})
        note(response.status_code, 0.0)
        if response.status_code == 201:
            self.held += 1

    @invariant()
    def never_oversold(self) -> None:
        taken = client.get("/admin/state").json()["taken"]
        assert taken <= SEATS
        assert self.held <= SEATS


Shop.TestCase.settings = settings(max_examples=10, stateful_step_count=CLIENTS, deadline=None)
test_shop = Shop.TestCase
