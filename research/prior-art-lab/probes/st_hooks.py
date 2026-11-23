"""Schemathesis hook: a custom check that reads the seat count after every response.

Loaded through SCHEMATHESIS_HOOKS=st_hooks. Schemathesis has no notion of a database
invariant, so this is the closest a user can get: ask the service after each call.
"""

import os

import httpx
import schemathesis

URL = os.environ.get("LAB_URL", "http://127.0.0.1:8765")
SEATS = int(os.environ.get("LAB_SEATS", "10"))


@schemathesis.check
def never_oversold(ctx, response, case):  # type: ignore[no-untyped-def]
    taken = httpx.get(f"{URL}/admin/state").json()["taken"]
    if taken > SEATS:
        raise AssertionError(f"oversold: {taken} reservations for {SEATS} seats")
