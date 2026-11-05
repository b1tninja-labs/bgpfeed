# Specification completeness -- and the roadmap it implies

This is the project's north star: every protocol obligation bgpfeed could plausibly take on,
with an honest status against the code at `HEAD`. It is blunt about gaps on purpose. A
roadmap that overstates its coverage is not a plan, it is marketing.

**The honesty rule:** a row may read `[ok]` only when a named test would fail if the
behaviour regressed. Reading the code and agreeing with it is not enough. That is how
"decoded but never sent" quietly becomes "implemented".

Legend: `[ok]` implemented and pinned by a named test -- `[part]` partial, with what is
missing stated -- `[ ]` not implemented -- `[no]` deliberate non-goal.

Update the affected row in the same commit that changes the behaviour. A row and its test
drift apart within one release, and the document becomes useless exactly when it is needed.

## 1. Obligations

| Obligation | Spec | Status | Where |
|---|---|---|---|
| `ris.subscribe()` | design | `[ ]` | `tests/test_obligations.py::subscribe` |
| `routeviews.follow()` | design | `[ ]` | `tests/test_obligations.py::follow` |
| `mrt.iter_updates()` | RFC 6396 | `[ ]` | `tests/test_obligations.py::iter_updates` |
| `state.checkpoint()` | design | `[ ]` | `tests/test_obligations.py::checkpoint` |
| `state.resume()` | design | `[ ]` | `tests/test_obligations.py::resume` |
| `budget.policy()` | design | `[ ]` | `tests/test_obligations.py::policy` |

## 2. Milestones

- M1 the shared event model, and MRT update reading through asnkit
- M2 RIS websocket client with reconnect and gap reporting
- M3 RouteViews delta poller with checkpoints
- M4 politeness and drop accounting
- M5 a replay fixture so downstream tests never touch the network
- M6 publication: 0.1.0

Every milestone is accepted by its rows above flipping to `[ok]` with a named test, not by
the code existing. Coverage in `pyproject.toml` ratchets in the same commit.

## 3. Errata watch

- RFC 6396 carries 2 verified errata.
- RIS and RouteViews are operational services, not specifications: pin the endpoint and message version in tests and expect change without notice.

## 4. Deliberate non-goals

| Non-goal | Status | Revisit when |
|---|---|---|
| storage or query indexes, which is asnkit | `[no]` | a named document requires it |
| analysis and alerting, which is routevalid | `[no]` | a named document requires it |
| running a collector: these are clients of other people's infrastructure | `[no]` | a named document requires it |

## 5. Open questions

- none recorded yet

## 6. Publication checklist

- [ ] every `[ ]` row above either `[ok]` or moved to a named later milestone
- [ ] `docs/research.md` claims re-verified and the dated ones either promoted or deleted
- [ ] interoperability evidence recorded in `docs/` against a non-Python implementation
- [ ] `tools/check_dist.py` proves the wheel ships the fixtures the README promises
- [ ] version 0.1.0 tagged, trusted publisher configured, README badges uncommented
