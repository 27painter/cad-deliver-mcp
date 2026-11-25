# cad-deliver-mcp

[![PyPI](https://img.shields.io/pypi/v/cad-deliver-mcp?logo=pypi)](https://pypi.org/project/cad-deliver-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

English | [中文](https://github.com/27painter/cad-deliver-mcp/blob/main/README.zh.md)

A pre-delivery gatekeeper for CAD artefacts: **stage, verify offline, then commit.**

It exists because *"the model said it finished"* is not a delivery. This server parses generated CAD files without launching any commercial CAD runtime, decides whether the drawing holds up against geometric and drafting rules, and returns `UNKNOWN` instead of `PASS` whenever a file cannot be inspected.

---

## Quick Start & MCP Client Setup

### Installation

```bash
pip install "cad-deliver-mcp[mcp]"   # CLI + MCP server
pip install cad-deliver-mcp          # CLI only
```

`ezdxf` and `PyMuPDF` are default dependencies on purpose: without them every DXF and every PDF would be reported as `UNKNOWN`, and a checker that can only say "could not judge" is not worth installing. To track the repository instead of a release:

```bash
pip install "cad-deliver-mcp[mcp] @ git+https://github.com/27painter/cad-deliver-mcp.git"
```

### Client Configuration (`mcp_config.json`)

Any MCP-capable client works — for example Codex CLI, Claude Code, or DeepSeek Harness. Add the following to its MCP configuration. Setting `PYTHONUTF8=1` is strongly recommended on Windows, because GB/T layer names and title-block attributes are Chinese text:

```json
{
  "mcpServers": {
    "cad-deliver": {
      "command": "python",
      "args": ["-m", "cad_deliver.server"],
      "env": {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

The package also registers two console scripts, so this is equivalent:

```json
{ "mcpServers": { "cad-deliver": { "command": "cad-deliver-mcp", "args": [] } } }
```

---

## The Three-Phase Commit Protocol

```text
deliver_stage(paths, profile="GB_T_TIER1")  ──▶  STAGED    (copy files, record SHA-256)
deliver_verify(staging_id)                  ──▶  VERIFIED  (offline deterministic check)
deliver_commit(staging_id, target_dir)      ──▶  COMMITTED (atomic release to target)
```

* **`deliver_commit` refuses anything that is not `VERIFIED`.**
* It re-hashes the staged bytes at commit time and refuses release if the file changed after verification.
* It refuses to overwrite an existing file in `target_dir` unless `overwrite=True` is passed explicitly — a filename collision is a version decision, and no `_1` or `_v2` suffix is ever invented.
* **`deliver://audit/{staging_id}`** exposes the full audit record as an MCP resource: file hashes, every verification attempt, structured findings, and deterministic fix instructions.

### What the State Machine Buys — and What It Does Not

It makes the gap between *"verified"* and *"released"* observable. An agent that edits a file after verification is caught by the SHA-256 comparison at commit time.

It is **not** a security sandbox. An agent can stage the same file again after editing it and obtain a clean `VERIFIED` state. The audit store tracks `attempts` and `history` so re-entry loops remain visible — a **protocol discipline**, not a security boundary.

### Atomic Storage & Protocol Isolation

* **Where files go:** Staging lives under `%TEMP%/cad-deliver-staging/<id>/` (`CAD_DELIVER_STAGING` overrides it). Nothing touches the user's delivery folder until commit. At commit, each file is written to `<target_dir>/<name>.partial`, flushed, and atomically promoted via `os.replace` — preventing half-written files on crash and avoiding cross-drive rename errors.
* **`stdout` is the protocol channel:** MCP over `stdio` carries JSON-RPC frames on `stdout`. `server.py` redirects `print` and configures `logging` to `stderr` at import time before transport initialization, ensuring stray diagnostics never corrupt a frame.

---

## Architecture & Repository Layout

```text
src/cad_deliver/
├── models.py          # ParsedDrawing, Check, Verdict, StageState — the core contract
├── core.py            # Constants and SHA-256 file digests
├── taxonomy.py        # Seven layer roles, aliases, and normalization
├── parsers/           # The ONLY layer allowed to import a CAD library
│   ├── dxf.py         #   ezdxf → ParsedDrawing
│   └── dwg.py         #   DWG → DXF conversion (ODA / LibreDWG / custom template)
├── geometry/          # Standard-agnostic geometric integrity checks
│   ├── dxf_checks.py  #   Dimensions, units, sheets, lineweights, fonts, dim-text vs geometry
│   ├── topology.py    #   Outline closure: dangling ends at a 0.01 mm tolerance
│   ├── pdf_checks.py  #   Page size and text layer verification
│   ├── step_checks.py #   FILE_SCHEMA, entity counts, raw coordinate bounding box
│   ├── model_checks.py
│   └── review_checks.py
├── standards.py       # Half-delivery profile: values validated against standards.json
├── pipeline.py        # Verification kernel: one path in, one verdict out
├── state_machine.py   # STAGED / VERIFIED / COMMITTED + persistent audit store
├── server.py          # MCP stdio surface: 3 tools + 1 audit resource
├── rules/             # Pluggable drafting standard rules
│   ├── base.py        #   BaseStandardRule(ABC) + registry
│   ├── codes.py       #   Stable machine codes (E_… / W_…)
│   ├── taxonomy.py    #   Compatibility re-export of cad_deliver.taxonomy
│   ├── registry.py    #   PROFILES + SEVERITY_PROFILES + runner
│   └── gb/            #   GB/T 14689 sheet, GB/T 4457.2 layers and closure, GB/T 10609.1 title block
└── cli.py             # Backward-compatible CLI invoked by dsh-sw-cad
```

### Enforced Orthogonal Layering

| Layer | Knows About | May Import |
| :--- | :--- | :--- |
| `parsers/` | Raw CAD formats (`.dxf`, `.dwg`, `.pdf`, `.step`) | `ezdxf`, `pymupdf` |
| `geometry/` | `ParsedDrawing` facts only (no drafting standard) | Standard library + `models` |
| `rules/` | `ParsedDrawing` facts + one specific drafting standard | Standard library + `models` |

A rule is a pure function of `ParsedDrawing`. It never opens files on disk and does not know which profile invoked it — the profile alone determines severity. `tests/test_layering.py` fails the test suite if either `geometry/` or `rules/` ever imports a CAD library.

Layering is enforced two ways, not one. The import check catches new dependencies; the *absence* of a live-document field on `ParsedDrawing` catches the other route — an implementation that smuggles the CAD object through an opaque field would pass an import scan and still read the document. `tests/test_parsers.py` asserts that attribute stays gone.

---

## Drafting Rules & Profiles

### Four Rules in `GB_T_TIER1`

| Rule ID | Standard | Blocks On |
| :--- | :--- | :--- |
| `gb.sheet_size` | GB/T 14689-2008 | Sheet dimensions outside A4–A0 (landscape or portrait, ±2 mm tolerance) |
| `gb.layer_taxonomy` | GB/T 4457.2-2003 | Dimension off its semantic layer, outline left on layer `0`, or unclassified layer name |
| `gb.closed_profile` | GB/T 4457.2-2003 | Contour ring leaving a dangling endpoint (`degree == 1` at `0.01 mm` tolerance) |
| `gb.title_block` | GB/T 10609.1-2008 | Missing title-block block reference, or blank mandatory attributes (`图名` / `图号` / `比例`) |

* **Why attribute-level title-block checks matter:** Checking block existence alone proves nothing — an empty title block still exists. `gb.title_block` inspects `ATTRIB` values and blocks when required fields are blank, catching the exact failure mode LLM agents produce.
* **Why endpoint-degree closure matters:** Real SolidWorks and NX exports frequently write visually closed rings with the DXF `closed` flag set to `False` and the final vertex coinciding with the first. Relying on the flag triggers false positives on valid industrial exports — *a gate that cries wolf gets switched off*. Endpoints are snapped at `0.01 mm` tolerance, flagging only true dangling vertices (`degree == 1`). Note that snapping must be a neighbourhood search, not `round(x / tolerance)`: rounding to a grid only joins points within half a cell, so a 0.008 mm round-trip artefact would still read as a break.

Every failure carries a concrete fix. A finding that only says "something is wrong" is noise to an agent; the closure rule reports the coordinates of the gap and what to do about it.

### Profiles & Severity Overrides

```python
PROFILES = {
    "LEGACY_COMPAT":  [],                 # Byte-compatible with dsh-sw-cad 2.2.0
    "GEOMETRY_ONLY":  [],                 # Generic geometric checks only, no drafting standard
    "GB_T_TIER1":     ["gb.sheet_size", "gb.layer_taxonomy", "gb.closed_profile", "gb.title_block"],
    "ISO_216_TIER1":  ["gb.sheet_size"],  # Same rule reused under ISO 216
}
```

`SEVERITY_PROFILES` maps machine codes (`E_TITLE_BLOCK`, `E_SHEET_SIZE`, etc.) to `ERROR` or `WARNING` per profile, allowing strict gating in `GB_T_TIER1` while preserving backward compatibility in `LEGACY_COMPAT`.

```python
from cad_deliver.rules import run_profile

for result in run_profile(drawing, "GB_T_TIER1"):
    print(result.code, result.severity.value, result.detail, result.fix)
```

---

## CLI Usage & Exit Codes

```bash
cad-deliver <dir|file>... [--profile LEGACY_COMPAT|GB_T_TIER1|GEOMETRY_ONLY] \
                           [--require drawing,pdf] [--out delivery.json] [--json] [--quiet]
```

* **Default Profile Difference:** The CLI defaults to `LEGACY_COMPAT` so existing `dsh-sw-cad` workflows retain exact backward compatibility, whereas the MCP server defaults to `GB_T_TIER1` so agents are gated strictly out of the box. `normal` and `half` are still accepted as legacy spellings of `LEGACY_COMPAT`.

| Exit Code | Meaning |
| :---: | :--- |
| **`0`** | **PASS** — The delivery holds up under the active profile |
| **`1`** | **FAIL** — One or more `ERROR`-level checks failed |
| **`2`** | **UNKNOWN** — Could not be judged (missing parser/converter or unreadable file) |

**`2` is never a pass.** A skipped check must never masquerade as success, because downstream agents read `PASS` and stop inspecting.

The contract holds even when the tool itself cannot run: if `cad-deliver-mcp` is not importable, the `dsh-sw-cad` entry point still writes a `delivery.json` with `verdict: unknown` and exits `2`. A missing report would be read by a caller as *"nothing to complain about"*.

---

## Supported Formats & Scope Boundaries

| Format | What Is Checked |
| :--- | :--- |
| **`.dxf`** | `DIMENSION` entities, semantic layer taxonomy, `$INSUNITS`, paper-space layouts, ISO 216 / GB/T 14689 sheet sizes, scale declarations, lineweight tiers, CJK fonts, overlapping dimension text, title-block attributes, outline closure, and overridden dimension text vs. underlying geometry |
| **`.dwg`** | Version tag; converted via ODA / LibreDWG when available and checked in full as `.dxf` |
| **`.pdf`** | Page dimensions against ISO 216 and presence of a real vector text layer |
| **`.step`** | `FILE_SCHEMA` (AP203 / AP214 / AP242), entity counts, and raw-coordinate bounding box |
| **`.sldprt` / `.sldasm`** | File presence, non-zero size, and binary signature (explicitly reports `UNKNOWN` for internal B-Rep geometry without native CAD runtime) |
| **`*_review_report.json`** | `evaluation.status`, empty issues list, non-empty checks block, and on-disk existence of claimed preview renders |

### Explicit Non-Goals

This gatekeeper does **not** judge engineering design intent: dimensional tolerances and fits (`H7/g6`), material selection, heat treatment, tolerance-stack closure, or manufacturability. A `PASS` guarantees structural and drafting-standard integrity — not shop-floor sign-off.

---

## Development & Roadmap

```bash
pip install -e ".[dev]"
pytest
```

The suites are also plain scripts, so pytest is optional:

```bash
python tests/test_rules.py
```

Individual test suites:
* `tests/test_layering.py` — Enforces zero CAD-library imports in `geometry/` and `rules/`
* `tests/test_geometry.py` & `tests/test_topology.py` — Bounding-box degeneracy, tolerance-snapped ring closure, and layer filtering
* `tests/test_rules.py` — 22 unit tests over pure in-memory `ParsedDrawing` fixtures
* `tests/test_server.py` — End-to-end `stage → verify → commit`, SHA-256 tamper rejection, and collision refusal
* `tests/test_legacy_compat.py` — Exit codes `0 / 1 / 2` and `LEGACY_COMPAT` gating parity
* `tests/test_packaging.py` — Version consistency and classifiers that PyPI would reject at upload time

### Roadmap
- [x] **Core Engine & 2PC MCP Server:** Orthogonal `ParsedDrawing` contract, `GB_T_TIER1` ruleset, atomic commit store, and `dsh-sw-cad` CLI integration.
- [ ] **50-Task Hybrid Benchmark (`benchmarks/`):** 15 anonymized real SolidWorks/NX exports + 15 parametric `ezdxf` fixtures + 20 deterministic fault-injected cases evaluating recall, false-positive rate, and latency across G1–G3 baselines.

## License

[MIT](LICENSE)