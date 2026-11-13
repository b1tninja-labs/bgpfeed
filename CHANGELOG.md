# Changelog

The format follows Keep a Changelog, and this project adheres to Semantic Versioning.

## Unreleased

### Added

- `model`: `Event`, `EventKind`, `Peer`, `Gap` and `GapReport`.
- `mrt.iter_updates`, `mrt.events_from_stream`, `mrt.Stats`: BGP4MP updates archives as events, through asnkit's MRT codec and pathattr's BGP decoding, with everything unmapped or malformed counted.
- `budget.DropCounter`: drops counted by reason.
- `routeviews.parse_name`, `parse_index`, `find_gaps`, `verify`, `Ledger`: archive file names, directory listings, gaps between files and pinned SHA-256 digests.
- `tools/fetch_corpus.py`, `tools/corpus.json`: real RouteViews and RIS directory listings fetched into a cache outside the repository, pinned by SHA-256 and size; `tests/test_routeviews_corpus.py` parses them and skips loudly without them.

### Changed

- The package namespace is lazy (PEP 562): `import bgpfeed.budget` imports neither asnkit nor pathattr.
- `tests/` is a package, so a sibling checkout on the path cannot shadow it.

### Fixed

- `routeviews.parse_index` read an nginx listing size with a unit (`394M`, as RIS prints it) as that many octets.

The rest of the package is a shell: the public surface exists as typed stubs that raise
`NotImplementedError`, and [ROADMAP.md](ROADMAP.md) lists what has to happen first.

## 0.0.0 - 2026-11-05

### Added

- Package skeleton, obligation matrix and CI gates for bgpfeed.
- `bgpfeed.apps` namespace reserved for composition that is not protocol behaviour.
