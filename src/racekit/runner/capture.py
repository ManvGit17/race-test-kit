"""What the runner records about one call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CallRecord:
    """One client's call in one round.

    ``released`` and ``ended`` are ``time.perf_counter()`` values: when the worker left the
    barrier and when its call returned or raised. They are comparable within one run only.
    """

    index: int
    released: float = 0.0
    ended: float = 0.0
    value: Any = None
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def latency_ms(self) -> float:
        return (self.ended - self.released) * 1000

    @property
    def status(self) -> int | None:
        """The HTTP status, if the call returned something with an integer ``status_code``.

        Duck typing keeps the runner free of any HTTP library: httpx and requests responses
        both have ``status_code``.
        """
        code = getattr(self.value, "status_code", None)
        return code if isinstance(code, int) else None
