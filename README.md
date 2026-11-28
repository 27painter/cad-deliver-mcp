# cad-deliver-mcp

[![PyPI](https://img.shields.io/pypi/v/cad-deliver-mcp?logo=pypi)](https://pypi.org/project/cad-deliver-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/27painter/cad-deliver-mcp/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24625649.svg)](https://doi.org/10.5281/zenodo.24625649)

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

### Rules and the Profiles That Enable Them

| Rule ID | Standard | Blocks On |
| :--- | :--- | :--- |
| `gb.sheet_size` | GB/T 14689-2008 | Sheet dimensions outside A4–A0 (landscape or portrait, ±2 mm tolerance) |
| `gb.layer_taxonomy` | GB/T 4457.2-2003 | Dimension off its semantic layer, outline left on layer `0`, or unclassified layer name |
| `gb.title_block` | GB/T 10609.1-2008 | Missing title-block block reference, or blank mandatory attributes (`图名` / `图号` / `比例`) |
| `gb.dim_text` | GB/T 4458.4-2003 | Dimension text override disagreeing with the measured value (>0.2% and >0.01 mm) |
| `geo.bbox_degenerate` | — | Model-space extent collapsed to a point or a line (<0.001 mm) |
| `gb.closed_profile` | GB/T 4457.2-2003 | Contour ring leaving a dangling endpoint (`degree == 1` at `0.01 mm` tolerance) — **`PROFILE_CLOSURE` only** |

`gb.closed_profile` is not in `GB_T_TIER1`. Closure is a property of a *single-view
profile drawing*; a multi-view engineering drawing is made of open edge segments, so
applying the rule there fires on 100% of real drawings, permanently. Enabling it is a
statement that the artefact is a profile drawing, which is why it lives in its own
profile rather than being tuned.

* **Why attribute-level title-block checks matter:** Checking block existence alone proves nothing — an empty title block still exists. `gb.title_block` inspects `ATTRIB` values and blocks when required fields are blank, catching the exact failure mode LLM agents produce.
* **Why endpoint-degree closure matters:** Real SolidWorks and NX exports frequently write visually closed rings with the DXF `closed` flag set to `False` and the final vertex coinciding with the first. Relying on the flag triggers false positives on valid industrial exports — *a gate that cries wolf gets switched off*. Endpoints are snapped at `0.01 mm` tolerance, flagging only true dangling vertices (`degree == 1`). Note that snapping must be a neighbourhood search, not `round(x / tolerance)`: rounding to a grid only joins points within half a cell, so a 0.008 mm round-trip artefact would still read as a break.

Every failure carries a concrete fix. A finding that only says "something is wrong" is noise to an agent; the closure rule reports the coordinates of the gap and what to do about it.

### Profiles & Severity Overrides

```python
PROFILES = {
    "LEGACY_COMPAT":   [],                # Byte-compatible with dsh-sw-cad 2.2.0
    "GEOMETRY_ONLY":   [],                # Generic geometric checks only, no drafting standard
    "GB_T_TIER1":      ["geo.bbox_degenerate", "gb.sheet_size", "gb.layer_taxonomy",
                        "gb.dim_text", "gb.title_block"],
    "PROFILE_CLOSURE": ["gb.closed_profile"],   # single-view profile drawings only
    "ISO_216_TIER1":   ["gb.sheet_size"],  # Same rule reused under ISO 216
}
```

`SEVERITY_PROFILES` maps machine codes (`E_TITLE_BLOCK`, `E_SHEET_SIZE`, etc.) to `ERROR` or `WARNING` per profile, allowing strict gating in `GB_T_TIER1` while preserving backward compatibility in `LEGACY_COMPAT`.

```python
from cad_deliver.rules import run_profile

for result in run_profile(drawing, "GB_T_TIER1"):
    print(result.code, result.severity.value, result.detail, result.fix)
```

---

## Benchmark: 50 Tasks, and an Ecosystem Contrast

`benchmarks/` holds a 50-task set built from three sources, run through five arms.

### What is in it

| Source | n | How it was made |
|---|---|---|
| `fixtures/gen` | 15 | Generated at A0–A4 in both orientations, all compliant |
| `fixtures/real` | 15 | **AutoCAD 2025**, native `Document.Export` to DXF, A4×5 / A3×7 / A2×3, scales 1:1 / 1:2 / 2:1, fifteen distinct part geometries |
| `fixtures/mutated` | 20 | 10 from real + 10 from generated, one injected defect each |

The five arms are cumulative: **G1** header only, **G2** header + geometry, **G2.5**
+ outline closure (the old `dsh-sw-cad` check set), **G3** the full rule set, and
**LEGACY_COMPAT** as the published-contract baseline.

### Results

```
| arm  | n  | FP | rate | CP 95% upper |
|------|---:|---:|-----:|-------------:|
| G1   | 30 |  0 | 0.0% |         9.5% |
| G2   | 30 |  0 | 0.0% |         9.5% |
| G2.5 | 30 |  0 | 0.0% |         9.5% |
| G3   | 30 |  0 | 0.0% |         9.5% |

Recall, G3: 20/20 by defect class — degenerate bbox 4/4, dimension on wrong layer 2/2,
missing title block 4/4, non-standard sheet 4/4, open profile 4/4, outline on layer 0 2/2.
G1, G2 and G2.5 catch none of the standard-level defects (0/16); LEGACY_COMPAT 0/20.

Latency per call, p50/p95 ms: G3 12.37 / 50.75, G2.5 10.30 / 43.88.
```

Both rates carry a bound, in both directions, computed the same way in pure Python:

| quantity | k/n | point estimate | CP 95% one-sided bound |
|---|---|---|---|
| recall | 20/20 | 100.0% | **86.1% lower** |
| false positives | 0/30 | 0.0% | **9.5% upper** |

Quoting "100% recall" or "0% false positives" without them would be a claim the sample
cannot support. 20 successes out of 20 is consistent with a true rate as low as 86%;
0 out of 30 is consistent with a true rate as high as 9.5%. Those are the numbers a
reviewer can argue with, which is the point of printing them.

### The ecosystem contrast is the interesting part

`fixtures/real_sw` holds the same fifteen parts exported by **SolidWorks 2025**
through its own API (`scripts/batch_export_sw.py`). Same gate, same rules:

```
| source            | CAD system | n  | PASS | FAIL | UNKNOWN |
|-------------------|------------|----|------|------|---------|
| `fixtures/real`   | AutoCAD    | 15 |   15 |    0 |       0 |
| `fixtures/real_sw`| SolidWorks | 15 |    0 |    2 |      13 |
```

**A SolidWorks DXF cannot be judged by a drafting-standard gate, and that is not a
defect in either side.** Its export carries no sheet format, writes every entity on
layer `0`, and gives the model space a plot-setting paper size. Three of the five
compliance dimensions therefore have nothing to look at:

| dimension | why there is nothing | verified how |
|---|---|---|
| sheet format / title block | `SaveAs`→DXF writes model geometry only | 129 registry export values, 818 preference toggles: no switch exists. `ISheet.SetTemplateName` and `InsertTitleBlockTable` both return `None`. `IPartDoc.ExportToDWG2` is the sheet-metal flat-pattern exporter |
| layer taxonomy | SolidWorks distinguishes line types by colour, not layer | `CreateLayer2` returns `True`; `Annotation.Layer` + `LayerOverride` assign without raising; the export still writes `0`. The mapping file's `[Entities]` section is ignored on the `SaveAs` path |
| sheet size | model space has no sheet | `NewDocument(template, 8, 0, 0)` builds an A3 sheet; the DXF still reports Letter for the `Model` layout |

A rule whose precondition does not hold abstains, and `CRITICAL_RULES` means an
abstention on title block, sheet size, layer taxonomy or closure turns the verdict
into `UNKNOWN` rather than `PASS`. **Five dimensions, two checked, is not a pass.**

This is the finding, not a shortcoming: the same rules that fully judge an AutoCAD
drawing have nothing to read in a SolidWorks export. That is why the benchmark's
compliant set is the AutoCAD one — and why the number above says `UNKNOWN` fifteen
times instead of quietly reporting `PASS`.

The two `FAIL`s are real and are not the contrast: `part-006` exported no dimensions
at all, and `part-013` carries a single dimension printed 1.33x its measured length —
one reading cannot prove a scale factor, so it is reported rather than excused. The
other thirteen abstain on all three dimensions and land on `UNKNOWN`.

`gb.dim_text` now recognises a scaled sheet: when every overridden dimension reads
the same multiple of the measured length (7x on eight dimensions, or 2x on two), the
view is scaled and the text states model values. A hand-edited text is a one-off
wrong number. A single mismatch is only excused when it lands on a standard drawing
scale, because one reading cannot establish a ratio.

### Does each rule earn its place?

Leave-one-out over the six rules, re-scoring all 50 tasks each time:

| removed rule | recall | drop | false positives |
|---|---|---:|---|
| (none — full set) | 20/20 | | 0/30 |
| `geo.bbox_degenerate` | 16/20 | −4 | 0/30 |
| `gb.sheet_size` | 16/20 | −4 | 0/30 |
| `gb.layer_taxonomy` | 16/20 | −4 | 0/30 |
| `gb.dim_text` | 20/20 | **0** | 0/30 |
| `gb.title_block` | 16/20 | −4 | 0/30 |
| `gb.closed_profile` | 16/20 | −4 | 0/30 |

Five rules each account for exactly the four samples of their defect class, and no
removal introduces a false positive — the rules do not paper over each other.

`gb.dim_text` shows zero because the 20 injected defects cover six classes and none is
a dimension-text mismatch. It is not idle in general: it is what fires on the SolidWorks
exports and what separates a scaled sheet from a wrong number. The zero measures the
benchmark's coverage, not the rule.

### Two baselines, measured rather than asserted

**AutoCAD CAD Standards (`.dws`).** A standards file compares *named objects* — layer
names and properties, linetypes, text styles, dimension styles. It caught **0 of 20**
injected defects, which is structural: every one is geometric or attribute-level, so no
sample introduces a new named object. It also cannot be automated end to end here —
`SaveAs` refuses every `.dws` format constant and `_-CHECKSTANDARDS` leaves no
machine-readable verdict — so the CSV records instrument reach, not a live run.

**Vision-language model.** `qwen3-vl-plus` over 65 renders:

| | rule layer | vision model |
|---|---|---|
| rejected | 20/20 | 19/20 |
| reason / code correct | **20/20** | **11/20** |
| false positives | **0/30** | **17/30** |
| machine-readable | per-rule code, evidence, fix | prose |

The 95% rejection rate is nearly double the 55% achieved once each finding is read and
checked against the injected defect — because the model refuses almost everything,
including 17 of 30 compliant drawings. By defect class the split is clean: geometry
4/4 and 3/4, title block 2/2 and 2/2, but **0/4 on sheet size and 0/2 on each of the two
layer defects**.

That is not a tuning problem. `E_CONTOUR_ON_ZERO` moves the outline to layer `0`, which
plots at colour 7 — the colour the outline layer already used, so the render is unchanged:
1 098 chromatic pixels out of 18 919 non-white (5.8%), against 1 150 out of 22 159 (5.2%)
for a compliant drawing (`max(R,G,B) - min(R,G,B) > 30/255`), with essentially all chromatic
pixels lying on the red ACI-1 centerlines (1 082 of 1 098; the remainder are anti-aliased edge
pixels of those same lines) and none on the part contour in either image.
**A layer name is not a picture.** Most of what GB/T regulates is naming and
attribution, which is precisely the part a reviewer that only looks cannot check.

Reproduce with:

```bash
python scripts/gen_acad_fixtures.py       # 15 AutoCAD drawings via COM + Document.Export
python scripts/batch_export_sw.py --input tmp_sw_parts --output benchmarks/fixtures/real_sw
python benchmarks/mutate.py               # 10 real + 10 generated, 20 defects
python benchmarks/run_eval.py             # tables, tasks.json, ablation_loo.csv
python scripts/render_dxf_png.py          # 65 PNGs into benchmarks/renders/
python scripts/eval_autocad_dws.py        # .dws reach, baseline_dws.csv
python benchmarks/eval_vlm.py             # needs VLM_BASE/VLM_KEY/VLM_MODEL
python benchmarks/score_vlm.py            # reason-matching against the injected defect
python -m pytest tests/ -q                # 74 tests
```

No exported DXF is post-processed by this project. What lands in `fixtures/` is what
the CAD application wrote.

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
* `tests/test_rules.py` — 28 unit tests over pure in-memory `ParsedDrawing` fixtures
* `tests/test_server.py` — End-to-end `stage → verify → commit`, SHA-256 tamper rejection, and collision refusal
* `tests/test_legacy_compat.py` — Exit codes `0 / 1 / 2` and `LEGACY_COMPAT` gating parity
* `tests/test_packaging.py` — Version consistency and classifiers that PyPI would reject at upload time

### Roadmap
- [x] **Core Engine & 2PC MCP Server:** Orthogonal `ParsedDrawing` contract, `GB_T_TIER1` ruleset, atomic commit store, and `dsh-sw-cad` CLI integration.
- [x] **50-Task Hybrid Benchmark (`benchmarks/`):** 15 anonymized real SolidWorks/NX exports + 15 parametric `ezdxf` fixtures + 20 deterministic fault-injected cases evaluating recall, false-positive rate, and latency across G1–G3 baselines.

## Archival Artifact & Citation

The frozen source code, 74-test suite, 50-drawing hybrid benchmark, 15-part AutoCAD 2025 / SolidWorks 2025 exports, 24 closed-loop repair runs, and reproducibility logs accompanying our paper (*Abstention Is Not a Pass: Pre-Delivery Verification for LLM-Generated CAD Drawings*, Aochen Wang, School of Mechanical Engineering, Liuzhou Institute of Technology) are permanently archived on Zenodo:

- **DOI:** [10.5281/zenodo.24625649](https://doi.org/10.5281/zenodo.24625649)

## License

[MIT](https://github.com/27painter/cad-deliver-mcp/blob/main/LICENSE)