# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version `1.0.0` is the first release where every number quoted in the README can
be reproduced from a file committed to this repository. Earlier releases could
not make that claim, which is the whole point of the project.

## [1.0.0] — 2026-11-28

### Added

- **Three-state verdict semantics.** `PASS` only when every required dimension
  actually ran, its preconditions held, and no blocking violation occurred.
  A dimension that could not be inspected yields `UNKNOWN` (exit code `2`),
  never a silent pass. `CRITICAL_RULES` turns an abstention on title block,
  sheet size, layer taxonomy or closure into `UNKNOWN` rather than `PASS`.
- **Rule pool / profile manifest / severity override separation.** A rule is a
  pure function of `ParsedDrawing`; the profile alone decides which rules run
  and how their findings are weighted.
- **Structured evidence and executable fixes.** Every finding carries the six
  auditable fields (`measured`, `expected`, `location`, `handle`, `count`,
  `name`) plus a concrete repair directive — `actionability` is 100% on the
  benchmark.
- **Two-phase commit MCP state machine** (`STAGED` → `VERIFIED` → `COMMITTED`)
  with SHA-256 re-verification at commit time, collision refusal, atomic
  `os.replace` promotion, and a `deliver://audit/{id}` resource.
- **50-task benchmark** (`benchmarks/`): 15 native AutoCAD 2025 exports,
  15 generated compliant drawings, 20 injected defects; five gating arms
  (G1, G2, G2.5, `LEGACY_COMPAT`, G3) with two-sided Clopper–Pearson bounds.
- **Leave-one-out rule ablation**, a measured AutoCAD `.dws` baseline, a
  vision-language baseline scored on rationale rather than refusal, and a
  cross-ecosystem study of the same 15 parts exported from SolidWorks 2025.
- **Query-level taxonomy** (`L0`–`L4`) and the scale-by-level interaction
  analysis over 24 closed-loop repair runs.
- `CHANGELOG.md`, `SECURITY.md`, `CITATION.cff`, `.gitattributes`, and CI
  (`verify.yml`) — the repository previously had none of these.

### Fixed

- The `[mcp]` extra resolved to `mcp` 2.x, where `mcp.server.fastmcp` no longer
  exists, so a fresh install failed 8 of 74 tests. The extra is now pinned to
  `mcp>=1.20,<2`; `benchmarks/results/pytest_repro.txt` records the exact
  environment and the `74 passed` run.
- README quoted latency figures (`G3 12.69 / 54.18`) that no committed file
  contained. It now reports the frozen snapshot from `latency.csv`
  (`12.37 / 50.75`, with `G2.5 10.30 / 43.88`).
- README described `tests/test_rules.py` as 22 unit tests; it has 28.
- Renderer defects found by reading its own output: omitted paperspace stripping
  borders, modelspace and paperspace plotted twice, and blank sheets on
  viewport-free layouts.
- `gb.dim_text` no longer blames a uniformly scaled sheet for a wrong dimension
  text: a consistent multiplier is recognised as scale, an isolated mismatch is
  reported.

### Changed

- Version `1.0.0`; PyPI classifier moved from `Development Status :: 3 - Alpha`
  to `5 - Production/Stable`.
- The 50-task benchmark roadmap item is complete, and the README says so.

## [0.2.0] — 2026-11-25

### Added

- First public release: `cad-deliver` CLI and `cad-deliver-mcp` MCP server,
  `GB_T_TIER1` / `LEGACY_COMPAT` / `GEOMETRY_ONLY` / `PROFILE_CLOSURE` /
  `ISO_216_TIER1` profiles, and the `dsh-sw-cad` compatibility entry point.
- Offline parsers for `.dxf`, `.dwg`, `.pdf`, `.step`, `.sldprt`/`.sldasm`, and
  `*_review_report.json`.
- Enforced orthogonal layering: `parsers/` is the only layer allowed to import a
  CAD library, checked by import scan and by the absence of a live-document
  field on `ParsedDrawing`.
