# bgpfeed

<!-- PyPI badges go live with the first release. Until then a version badge renders
     "no version" on the landing page, which reads as a defect rather than a date, so
     the badges stay commented out until the tag exists.
-->

**Pre-alpha shell.** The package surface, the obligation matrix and the CI gates exist.
No protocol behaviour is implemented: every public function raises `NotImplementedError`,
and the test suite records that rather than hiding it. Read
[ROADMAP.md](ROADMAP.md) before depending on any of it.

bgpfeed -- RIPE RIS and RouteViews, without the C dependency

A looking glass that only shows your own routers is a status page. The upstream view comes from RIPE RIS and RouteViews, and in Python that means the bgpstream C library with its build headaches, or hand written FTP polling. Neither name is taken on PyPI: bgpstream, ris and routeviews are all absent as of 2026-11-05. bgpfeed is the small honest client for both, emitting the same objects bmpkit emits, so anything built on one works with the other.

## The gap, with a date

PyPI was queried on 2026-11-05 for this name and for every neighbouring project. Landscape
claims rot quickly: two projects in this portfolio shipped within five days of the survey,
which is why the table below carries dates instead of adjectives.

| Project | Version | Last release | Why it is not this project |
|---|---|---|---|
| bgpstream | - | - | the C library everyone wraps; absent from PyPI (2026-11-05) |
| ris, routeviews, bgpfeed | - | - | all free on PyPI (2026-11-05) |
| exabgp rib scripts | - | - | ad hoc pollers, not a resumable client |

What this project intends to add:

- a RIS websocket client with viewer selection, reconnect and gap detection
- a RouteViews delta poller that checkpoints by file and never re-reads or skips silently
- one normalised event model across live feeds, archives and BMP sessions
- backpressure and drop accounting, so a slow analyst does not silently lose updates
- honest rate limiting that respects the operators running these services

## Specification spine

Status and publication dates below were read from the RFC Editor record on 2026-11-05. A
section number is cited only where that section was read in full; everything else cites the
document, which is the honest grain size for a plan. See [docs/rfc-map.md](docs/rfc-map.md).

| Document | Status | Published | What it gives this project |
|---|---|---|---|
| RFC 6396 | Proposed Standard | 2011-10 | MRT, the format RouteViews publishes its updates in |
| RIPE RIS live API | operational practice | - | the websocket protocol, viewer selection and message shape |
| RouteViews archive layout | operational practice | - | per collector hourly directories, file naming and retention |

### Errata watch

- RFC 6396 carries 2 verified errata.
- RIS and RouteViews are operational services, not specifications: pin the endpoint and message version in tests and expect change without notice.

## Module layout

| Module | Responsibility |
|---|---|
| `model` | the common event and update objects shared with bmpkit |
| `ris` | the websocket protocol, viewers and resubscription |
| `routeviews` | archive discovery, delta polling and checkpoints |
| `mrt` | UPDATE_FILE and TABLE_DUMP reading via asnkit |
| `state` | resume points and gap accounting per source |
| `budget` | politeness: concurrency caps, jitter and backoff |

## What it does not do

- storage or query indexes, which is asnkit
- analysis and alerting, which is routevalid
- running a collector: these are clients of other people's infrastructure


## Install

```bash
git clone https://github.com/b1tninja/bgpfeed.git
cd bgpfeed
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
```

Not published to PyPI yet. The name is reserved for this repository's trusted publisher at
the moment of the first release.

## Development

All four gates must pass, on Linux and Windows alike:

```bash
ruff check . && ruff format --check .
mypy bgpfeed
pytest -q --cov
python -O -m pytest -q
```

The last line is the one that matters most in a protocol library. `-O` strips `assert`, and a
parser whose bounds checks were asserts stops being a parser under production flags. Wire
paths raise named exceptions; asserts belong in tests and nowhere else.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
