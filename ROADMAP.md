# Specification completeness -- and the roadmap it implies

This is the project's north star: every protocol obligation bgpfeed could plausibly take on,
with an honest status against the code at `HEAD`. It is blunt about gaps on purpose. A
roadmap that overstates its coverage is not a plan, it is marketing.

**The honesty rule:** a row may read `[ok]` only when a named test would fail if the
behaviour regressed. Reading the code and agreeing with it is not enough. That is how
"decoded but never sent" quietly becomes "implemented".

Legend: `[ok]` implemented and pinned by a named test -- `[part]` partial, with what is
missing stated -- `[ ]` not implemented -- `[no]` deliberate non-goal.

A Where cell marked `(to be written)` names the test that will pin the row once it exists; no
such test has been written yet, and the row cannot leave `[ ]` until it has. The Milestone
column places the row on the ladder in section 2, and `-` means it is not placed yet.

Update the affected row in the same commit that changes the behaviour. A row and its test
drift apart within one release, and the document becomes useless exactly when it is needed.

## 1. Obligations

| Obligation | Spec | Status | Where | Milestone |
|---|---|---|---|---|
| `ris.subscribe()`: split into frame codec (if we own a client), subscription message builder, JSON-to-event mapping and reconnect policy; transport is an owner decision, section 5 | design | `[ ]` | `tests/test_obligations.py::test_subscribe` (to be written) | M2 |
| `routeviews.follow()` | design | `[ ]` | `tests/test_obligations.py::test_follow` (to be written) | M3 |
| `mrt.iter_updates()`: reworded as a mapping function, MRT BGP4MP record to event. The MRT codec itself is owned by asnkit (`asnkit.mrt`, see section 5); this row covers only the mapping, including the `_ADDPATH` subtypes 8-11 of RFC 8050 | RFC 6396 section 4.4, RFC 8050 section 3 | `[ ]` | `tests/test_obligations.py::test_iter_updates` (to be written) | M1 |
| `state.checkpoint()`: atomic write of a hash-protected `Checkpoint` to a caller-named `StateStore` directory; refuses to rewind unless asked | design: a stored checkpoint resumes exactly, or refuses | `[ok]` | `tests/test_state.py::test_checkpoint_is_atomic_under_crash`, `tests/test_state.py::test_checkpoint_monotonic_guard`, `tests/test_state.py::test_source_with_path_traversal_is_confined` | M3 |
| `state.resume()`: None only when nothing was stored; corrupt, truncated, wrong-schema, hash-mismatched or swapped files raise `StateError` | design | `[ok]` | `tests/test_state.py::test_roundtrip`, `tests/test_state.py::test_resume_hash_of_record_mismatch_raises`, `tests/test_state.py::test_resume_corrupt_json_raises` | M3 |
| `budget.policy()`: validated `Budget` with no defaults (operator rules not yet recorded); `budget.Gate` enforces `max_concurrent`, spacing and full-jitter backoff with injectable clock, rng and sleep | design: never exceeds `max_concurrent`, spaces requests by at least the interval | `[ok]` | `tests/test_budget.py::test_never_exceeds_max_concurrent`, `tests/test_budget.py::test_min_interval_enforced_with_fake_clock`, `tests/test_budget.py::test_cancelled_waiter_releases_slot` | M4 |
| `model.Event`: the shared event schema (one row); who owns it with bmpkit is undecided (recommend bgpfeed owns it only if bmpkit imports it) | design | `[ ]` | `tests/test_obligations.py::test_event_schema` (to be written) | M1 |
| `model.GapReport`, `budget.DropCounter` and `Stream.stats()`: gap and drop accounting as a first-class output (README promises it) | design | `[ ]` | `tests/test_obligations.py::test_gap_report` (to be written) | M4 |
| `routeviews.index_parse()` (directory listing parse, fixture-pinned) and `fetch.verify()` (record the sha256 of each archive; GET over HTTPS is not a signature) | operational practice | `[ ]` | `tests/test_obligations.py::test_index_parse` (to be written) | M3 |
| `ris.reconnect_policy()`: backoff with jitter. `Gate.next_retry_delay` supplies the delays; the reconnect wiring and gap detection are not built | design | `[ ]` | `tests/test_obligations.py::test_reconnect` (to be written) | M2 |
| M5 replay fixture: recorded RIS and RouteViews captures so the live rows are closed offline; do this before M2 and M3 | design | `[ ]` | `tests/test_obligations.py::test_replay_fixture` (to be written) | M5 |

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

- RFC 6396 carries 2 verified errata, both in Appendix A example bytes; any vector copied from it uses the corrected bytes (see `asnkit/docs/rfc-map.md`).
- RFC 8050 (MRT with ADD-PATH, Proposed Standard, 2017-05, no errata, not marked as updating RFC 6396): the BGP4MP `_ADDPATH` subtypes 8-11 carry the same BGP message with ADD-PATH NLRI; an update reader that ignores them misreads the NLRI.
- RIS and RouteViews are operational services, not specifications: pin the endpoint and message version in tests and expect change without notice.

## 4. Deliberate non-goals

| Non-goal | Status | Revisit when |
|---|---|---|
| storage or query indexes, which is asnkit | `[no]` | a named document requires it |
| analysis and alerting, which is routevalid | `[no]` | a named document requires it |
| running a collector: these are clients of other people's infrastructure | `[no]` | a named document requires it |

## 5. Open questions

- M5 now has a row (replay fixture). Order it before M2 and M3, since the live rows can only be closed by recorded captures.
- **Owner decision, with recommendation: who owns MRT parsing.** The plan had two MRT readers, `asnkit.mrt.iter_records` and `bgpfeed.mrt.iter_updates`, both RFC 6396. Recommendation: asnkit owns MRT parsing (common header, TABLE_DUMP_V2, BGP4MP, ADD-PATH subtypes; asnkit now implements the common header and PEER_INDEX_TABLE and has a row for `mrt.iter_bgp4mp`); bgpfeed imports it and keeps only fetch, checkpoint and the BGP4MP-to-event mapping. That is why the `mrt.iter_updates` row above is a mapping function. Reasons: one codec to fix when an erratum lands, and the M1 text already says "through asnkit". Status: recommended, awaiting the owner. Consequence: bgpfeed also needs pathattr for UPDATE contents.
- **Owner decision: RIS Live transport.** RIS Live is delivered over WebSocket (RFC 6455: Proposed Standard, updated by RFC 7936, RFC 8307, RFC 8441, 3 verified errata, as the research review reports; re-check through rfclib before use). The standard library has no WebSocket client. Options: (a) a new small portfolio project implementing a stdlib WebSocket client (its name must pass `projecthub shells names`); (b) a plain HTTP streaming path, if RIPE offers one, which needs no new client; (c) a non-goal: bgpfeed covers RouteViews and archives only and RIS Live is out of scope. Not verified: whether RIS Live offers plain HTTP streaming. The RIPE pages tried on 2026-11-13 (ris-live.ripe.net) returned 404 and nothing was guessed; check the RIPE documentation first, since (b) removes the dependency. Recommendation: (b) if it exists, else (c) for 0.1.0 and (a) later. `ris.subscribe` stays `[ ]` meanwhile.
- Operator usage rules (RIPE RIS, RouteViews) are not yet recorded in `docs/research.md`; `budget.policy` therefore has no default rates, and choosing defaults is blocked on recording them with a URL and date.
- bgpfeed `docs/plan.md` lists asnkit as the blocker; the real prerequisites are pathattr (UPDATE decoding), a WebSocket answer, and hash-recorded HTTPS fetch. A feed consumes asnkit; it does not need it to fetch or checkpoint.

## 6. Publication checklist

- [ ] every `[ ]` row above either `[ok]` or moved to a named later milestone
- [ ] `docs/research.md` claims re-verified and the dated ones either promoted or deleted
- [ ] interoperability evidence recorded in `docs/` against a non-Python implementation
- [ ] `tools/check_dist.py` proves the wheel ships the fixtures the README promises
- [ ] version 0.1.0 tagged, trusted publisher configured, README badges uncommented
