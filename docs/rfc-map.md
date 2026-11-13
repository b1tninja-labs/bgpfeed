# Where every claim in this repository comes from

| Document | Status | Published | Verified against the publisher record on |
|---|---|---|---|
| RFC 6396 | Proposed Standard | 2011-10 | 2026-11-05 |
| RFC 8050 | Proposed Standard, current, no errata (read 2026-11-13) | 2017-05 | 2026-11-13 |
| RFC 4271 | Draft Standard, current; section 4.3 (UPDATE format, attribute framing) read 2026-11-13 | 2006-01 | 2026-11-13 |
| RFC 7606 | Proposed Standard, current, 1 erratum on file and none verified; section 3 read in full 2026-11-13: (d) a missing well-known mandatory attribute is treat-as-withdraw, (g) a repeated MP_REACH or MP_UNREACH is a session reset, (h) the strongest approach wins, (j) a fault that stops the NLRI being located is session reset or AFI/SAFI disable | 2015-08 | 2026-11-13 |
| RFC 7911 | Proposed Standard, current, no errata; section 3 read 2026-11-13 (a 4-octet Path Identifier prepended to each NLRI entry); section 5, which says where it is used, was not read here | 2016-07 | 2026-11-13 |
| RFC 4760 | Draft Standard, current; MP_REACH_NLRI and MP_UNREACH_NLRI are decoded by pathattr, which cites it; not read in this session | 2007-01 | 2026-11-13 |
| RIPE RIS live API | operational practice | - | 2026-11-05 |
| RouteViews archive layout | operational practice | - | 2026-11-05 |

Citation rules, in the order they most often get broken:

1. Cite the document. A secondary write-up is a lead, not a source.
2. A section number is cited only if that section was read in full.
3. Errata are checked at each milestone freeze, not once at the start.
4. Where a claim came from a body outside the RFC series, that body is named here.

Operational sources (not RFCs, none fetched in the 2026-11-13 session): the RouteViews and RIS archive file names `updates.YYYYMMDD.HHMM.bz2` / `.gz`, `rib.` and `bview.`, and the two common directory-listing shapes. `bgpfeed.routeviews` is written from those conventions and its tests build the pages; the real-capture row in ROADMAP.md replaces them. The ADD-PATH subtypes of RFC 8050 section 3 do not say which address families carry Path Identifiers; that is the row `mrt.addpath-families`.

Re-verify with the RFC library rather than memory: `info('RFCnnnn')` for current status, `errata('RFCnnnn')` for corrections, and `read('RFCnnnn', view='normative')` for the MUST and SHOULD statements that become obligation rows.
