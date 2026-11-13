"""politeness: concurrency caps, jitter and backoff.

The operators of RIPE RIS and RouteViews publish their own usage terms; those are operational
sources, not RFCs, and no default rate here is taken from them. Every number is therefore a
required argument: ``policy`` has no defaults to be aggressive by accident. The clock, the
random generator and the sleep function are injectable so tests never wait.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

__all__ = [
    "Budget",
    "Gate",
    "policy",
]

_MAX_DOUBLINGS = 60


@dataclass(frozen=True)
class Budget:
    """A validated politeness budget."""

    max_concurrent: int
    min_interval: timedelta
    jitter: timedelta
    retry_base: timedelta
    retry_max: timedelta

    def retry_ceiling(self, attempt: int) -> timedelta:
        """Upper bound of the delay before retry ``attempt`` (0-based): doubling, capped."""
        if attempt < 0:
            raise ValueError("attempt must not be negative")
        micro = timedelta(microseconds=1)
        scaled = (self.retry_base // micro) << min(attempt, _MAX_DOUBLINGS)
        return timedelta(microseconds=min(self.retry_max // micro, scaled))


def policy(
    max_concurrent: int,
    jitter: timedelta,
    *,
    min_interval: timedelta,
    retry_base: timedelta,
    retry_max: timedelta,
) -> Budget:
    """Validate and return a :class:`Budget`.

    Behaviour defined by design: never exceeds ``max_concurrent`` and spaces requests by at
    least ``min_interval`` plus a random extra of up to ``jitter`` (see :class:`Gate`).
    """
    zero = timedelta(0)
    if type(max_concurrent) is not int or max_concurrent < 1:
        raise ValueError("max_concurrent must be an integer of at least 1")
    if jitter < zero:
        raise ValueError("jitter must not be negative")
    if min_interval < zero:
        raise ValueError("min_interval must not be negative")
    if retry_base <= zero:
        raise ValueError("retry_base must be positive")
    if retry_max < retry_base:
        raise ValueError("retry_max must be at least retry_base")
    return Budget(max_concurrent, min_interval, jitter, retry_base, retry_max)


class Gate:
    """Enforces a :class:`Budget` on concurrent callers (one event loop)."""

    def __init__(
        self,
        budget: Budget,
        *,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.budget = budget
        self._rng = rng if rng is not None else random.Random()  # noqa: S311 - jitter, not a secret
        self._clock = clock
        self._sleep = sleep
        self._slots = asyncio.Semaphore(budget.max_concurrent)
        self._spacing = asyncio.Lock()
        self._next_allowed = float("-inf")

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold one of the concurrent slots, starting no sooner than the spacing allows.

        The slot is released on exit, on an exception in the holder, and on cancellation.
        """
        async with self._slots:
            async with self._spacing:
                wait = self._next_allowed - self._clock()
                if wait > 0:
                    await self._sleep(wait)
                extra = self._rng.uniform(0.0, self.budget.jitter.total_seconds())
                gap = self.budget.min_interval.total_seconds() + extra
                self._next_allowed = self._clock() + gap
            yield

    def next_retry_delay(self, attempt: int) -> timedelta:
        """Full-jitter backoff: uniform in [0, ``retry_ceiling(attempt)``]."""
        ceiling = self.budget.retry_ceiling(attempt).total_seconds()
        return timedelta(seconds=self._rng.uniform(0.0, ceiling))
