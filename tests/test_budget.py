"""Politeness budget, with a fake clock and no real sleeping."""

from __future__ import annotations

import asyncio
import itertools
import random
from datetime import timedelta

import pytest

from bgpfeed.budget import Budget, Gate, policy

S = timedelta(seconds=1)


def make(max_concurrent=2, jitter=0.5, interval=1.0, base=1.0, cap=30.0):
    return policy(
        max_concurrent,
        S * jitter,
        min_interval=S * interval,
        retry_base=S * base,
        retry_max=S * cap,
    )


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)


def gate(budget, seed=1):
    ft = FakeTime()
    return Gate(budget, rng=random.Random(seed), clock=ft.clock, sleep=ft.sleep), ft


def test_policy_returns_budget():
    b = make()
    assert isinstance(b, Budget)
    assert b.max_concurrent == 2


@pytest.mark.parametrize("n", [0, -1, True, 1.5])
def test_zero_or_negative_concurrency_rejected(n):
    with pytest.raises(ValueError, match="max_concurrent"):
        make(max_concurrent=n)


def test_negative_values_rejected():
    with pytest.raises(ValueError, match="jitter"):
        make(jitter=-0.1)
    with pytest.raises(ValueError, match="min_interval"):
        make(interval=-1)
    with pytest.raises(ValueError, match="retry_base"):
        make(base=0)
    with pytest.raises(ValueError, match="retry_max"):
        make(base=5, cap=1)


def test_policy_has_no_defaults():
    with pytest.raises(TypeError):
        policy(1, S)


async def test_never_exceeds_max_concurrent():
    g, _ = gate(make(max_concurrent=3, jitter=0, interval=0))
    active = peak = 0

    async def worker():
        nonlocal active, peak
        async with g.slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(25)))
    assert peak == 3


async def test_min_interval_enforced_with_fake_clock():
    g, ft = gate(make(max_concurrent=5, jitter=0, interval=2.0))
    starts = []

    async def worker():
        async with g.slot():
            starts.append(ft.now)

    await asyncio.gather(*(worker() for _ in range(6)))
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert len(starts) == 6
    assert all(gap >= 2.0 - 1e-9 for gap in gaps)


async def test_spacing_includes_jitter_within_bounds():
    g, ft = gate(make(max_concurrent=5, jitter=0.5, interval=1.0), seed=42)
    starts = []

    async def worker():
        async with g.slot():
            starts.append(ft.now)

    await asyncio.gather(*(worker() for _ in range(30)))
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert all(1.0 - 1e-9 <= gap <= 1.5 + 1e-9 for gap in gaps)
    assert max(gaps) > min(gaps)  # the jitter is actually applied


def test_backoff_ceiling_monotone_and_capped():
    b = make(base=1.0, cap=30.0)
    ceilings = [b.retry_ceiling(n) for n in range(0, 200)]
    assert ceilings == sorted(ceilings)
    assert ceilings[0] == S
    assert ceilings[3] == 8 * S
    assert ceilings[-1] == 30 * S
    with pytest.raises(ValueError, match="attempt"):
        b.retry_ceiling(-1)


def test_jitter_within_bounds():
    g, _ = gate(make(base=1.0, cap=30.0), seed=5)
    for attempt in range(12):
        ceiling = g.budget.retry_ceiling(attempt)
        for _ in range(50):
            assert timedelta(0) <= g.next_retry_delay(attempt) <= ceiling


def test_same_seed_same_delays():
    a, _ = gate(make(), seed=9)
    b, _ = gate(make(), seed=9)
    assert [a.next_retry_delay(n) for n in range(8)] == [b.next_retry_delay(n) for n in range(8)]


async def test_cancelled_waiter_releases_slot():
    g, _ = gate(make(max_concurrent=1, jitter=0, interval=0))
    gate_open = asyncio.Event()

    async def holder():
        async with g.slot():
            await gate_open.wait()

    first = asyncio.create_task(holder())
    await asyncio.sleep(0)
    waiter = asyncio.create_task(holder())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    gate_open.set()
    await first
    async with asyncio.timeout(1), g.slot():
        pass  # would hang if the cancelled waiter had leaked the slot


async def test_exception_in_holder_releases_slot():
    g, _ = gate(make(max_concurrent=1, jitter=0, interval=0))
    with pytest.raises(RuntimeError, match="boom"):
        async with g.slot():
            raise RuntimeError("boom")
    async with asyncio.timeout(1), g.slot():
        pass
