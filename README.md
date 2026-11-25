# cad-deliver-mcp

[![PyPI](https://img.shields.io/pypi/v/cad-deliver-mcp?logo=pypi)](https://pypi.org/project/cad-deliver-mcp/)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)

English | [中文](https://github.com/27painter/cad-deliver-mcp/blob/main/README.zh.md)

A pre-delivery gatekeeper for CAD artefacts: **stage**, **verify offline**, then **commit**.

It exists because "the model said it finished" is not a delivery. This server reads what the job
produced and decides whether it holds up — and when it cannot read something, it says `UNKNOWN`
instead of `PASS`.

> Status: **phase 3 complete**. The parsing and checking logic was migrated here from
> [`dsh-sw-cad`](https://github.com/27painter/dsh-sw-cad) with byte-for-byte identical behaviour,
> verified by a field-by-field comparison across 12 cases before the frozen baseline was retired.
> The rule layer, the MCP surface and the state machine are in place.
> **Not done yet:** the 50-task benchmark (`benchmarks/`), which is why there is no recall figure
> in this file.

## The three calls

```
deliver_stage(paths, profile="GB_T_TIER1")   copy files, record SHA-256  -> STAGED
deliver_verify(staging_id)                   judge offline               -> VERIFIED / FAILED
deliver_commit(staging_id, target_dir)       release, atomically         -> COMMITTED
```

`commit` refuses anything that is not `VERIFIED`. It re-hashes the staged bytes
and refuses if they changed since staging. It refuses to overwrite an existing
file unless `overwrite=true` is passed explicitly — a name collision is a version
decision, and **no `_1` / `_v2` suffix is invented**.

`deliver://audit/{staging_id}` returns the whole record: hashes, every verify
attempt, findings and fixes.

### What the state machine buys, and what it does not

It makes the gap between "verified" and "released" observable. An agent that edits
a file after verification is caught by the hash comparison at commit time.

It is **not** a security boundary. An agent can stage the same file again after
editing it and get a clean `VERIFIED`. The record counts attempts
(`attempts`, `history`) so re-entry is visible in the audit — a protocol
discipline, not a sandbox.

### Where files go

Staging lives under `%TEMP%/cad-deliver-staging/<id>/` (`CAD_DELIVER_STAGING`
overrides it). Nothing is written next to the user's drawings until commit. At
commit, each file lands as `<name>.partial` **inside the target folder**, is
flushed, and is then `os.replace`d to its final name — so a crash leaves either
the previous state or a `.partial`, never a half-written file under the real
name, and the rename stays atomic across drives.

### stdout is the protocol channel

MCP over stdio carries JSON-RPC frames on stdout. `server.py` points `print` at
stderr and configures logging to stderr **at import time, before the transport
starts**, so a stray diagnostic cannot corrupt a frame. `sys.stdout` itself is
left alone, because the transport writes through it.

---

## Layout

```
src/cad_deliver/
├── models.py          # ParsedDrawing, Check, Verdict, StageState — the contract
├── core.py            # constants and file digests
├── taxonomy.py        # seven layer roles, aliases, normalisation (shared by geometry/ and rules/)
├── parsers/           # the only layer allowed to import a CAD library
│   ├── dxf.py         #   ezdxf → ParsedDrawing
│   └── dwg.py         #   DWG → DXF conversion (ODA / LibreDWG / custom template)
├── geometry/          # checks that know nothing about any standard
│   ├── dxf_checks.py  #   dimensions, units, sheets, lineweights, fonts, dim text vs geometry
│   ├── topology.py    #   outline closure: dangling ends at a 0.01 mm tolerance
│   ├── pdf_checks.py  #   page size, text layer
│   ├── step_checks.py #   schema, entity counts, bounding box
│   ├── model_checks.py
│   └── review_checks.py
├── standards.py       # half-delivery profile: values must come from standards.json
├── pipeline.py        # the verification kernel: one path in, one verdict out
├── state_machine.py   # STAGED/VERIFIED/COMMITTED + the staging store
├── server.py          # MCP stdio surface: 3 tools + 1 audit resource
├── rules/             # pluggable standard rules
│   ├── base.py        #   BaseStandardRule(ABC) + registry
│   ├── codes.py       #   stable machine codes (E_… / W_…)
│   ├── taxonomy.py    #   compatibility re-export of cad_deliver.taxonomy
│   ├── registry.py    #   PROFILES + SEVERITY_PROFILES + runner
│   └── gb/            #   GB/T 14689 sheet, GB/T 4457.2 layers, GB/T 10609.1 title block
└── cli.py             # the CLI dsh-sw-cad still calls
```

## The rule layer

Two layers, and the split is enforced rather than described:

| layer | knows about | may import |
|---|---|---|
| `geometry/` | parsed facts, no standard | nothing CAD |
| `rules/` | parsed facts, one standard each | nothing CAD |

A rule is a pure function of `ParsedDrawing`. It does not open files and does not
know which profile called it — the profile only decides what a finding *costs*.
That is what makes a new standard a plugin instead of a fork.

`tests/test_layering.py` fails the build when either layer imports a CAD library.
The phase-1 debt list is now empty and the test asserts it stays that way.

### Four rules, one Tier-1 profile

| rule | standard | blocks on |
|---|---|---|
| `gb.sheet_size` | GB/T 14689-2008 | a sheet that is not A4–A0 (either orientation, ±2 mm) |
| `gb.layer_taxonomy` | GB/T 4457.2-2003 | a dimension off its layer, an outline left on layer 0, an unclassifiable layer name |
| `gb.closed_profile` | GB/T 4457.2-2003 | an outline that leaves a dangling end |
| `gb.title_block` | GB/T 10609.1-2008 | no title block, or a required field (图名/图号/比例) present but empty |

The title-block rule is the one that matters most. Checking that a block exists
proves nothing — an empty title block still exists. It reads the attributes and
fails when a required field is blank, which is the failure an agent actually
produces.

Closure is decided by endpoints, not by the `closed` flag. Real SolidWorks and NX
exports write a closed ring with the flag off and the last vertex on the first, so
the flag alone reports every one of those as broken — a gate that cries wolf gets
switched off. Endpoints are joined at a 0.01 mm tolerance, and a vertex with
degree 1 is a dangling end.

### Profiles

```python
PROFILES = {
    "LEGACY_COMPAT":  [],                 # no GB rule: byte-compatible with dsh-sw-cad 2.2.0
    "GEOMETRY_ONLY":  [],                 # generic checks only, no standard
    "GB_T_TIER1":     ["gb.sheet_size", "gb.layer_taxonomy", "gb.closed_profile", "gb.title_block"],
    "ISO_216_TIER1":  ["gb.sheet_size"],  # same rule, different standard
}
```

`SEVERITY_PROFILES` maps a code to a severity per profile, so `E_TITLE_BLOCK` can
warn in one profile and block in another **without a rule changing**.

```python
from cad_deliver.rules import run_profile

for result in run_profile(drawing, "GB_T_TIER1"):
    print(result.code, result.severity.value, result.detail, result.fix)
```

## CLI

```bash
cad-deliver <dir|file>... [--profile LEGACY_COMPAT|GB_T_TIER1|GEOMETRY_ONLY] \
                           [--require drawing,pdf] [--out delivery.json] [--json] [--quiet]
```

`--profile` defaults to `LEGACY_COMPAT`. The MCP server defaults to `GB_T_TIER1`
instead — a caller that has to opt in to the standard will never see it, while an
existing `dsh-sw-cad deliver` call must keep meaning exactly what it meant before.

`normal` and `half` are still accepted as legacy spellings: they select the
compatible rule set with or without the half-delivery value table.

Exit codes, and the reason there are three:

| code | meaning |
|---:|---|
| 0 | the delivery holds up |
| 1 | it does not |
| 2 | **it could not be judged** — a reader was missing, so part of the delivery was never examined |

`2` is never a pass. A check that was skipped must not be reported as one that succeeded, because the
caller reads `PASS` and stops looking.

This is not hypothetical: an earlier version returned `PASS` for every DXF on a machine without
`ezdxf`, because the import failure was recorded as a warning and warnings did not affect the
verdict.

## What it reads

| kind | what is actually checked |
|---|---|
| `.dxf` | DIMENSION entities, layer table, `$INSUNITS`, paper-space content, sheet size against ISO 216, a stated 比例/SCALE, line-weight tiers, CJK fonts, overlapping dimension texts, title-block clues, outline closure, and **overridden dimension text against the geometry it annotates** |
| `.dwg` | the version tag; with a converter present it is converted and checked in full as a DXF |
| `.pdf` | page size against ISO 216, and whether the text layer is real |
| `.step` | `FILE_SCHEMA` → AP203/214/242, entity counts, bounding box from raw coordinates |
| `.sldprt` / `.sldasm` | presence, size, signature — geometry needs the application, and it says so |
| `*_review_report.json` | `evaluation.status`, empty `issues`, **plus** a non-empty `checks` block, true preview flags, and an actual image on disk whenever previews are claimed |

## What it does not check

Tolerances and fits (`H7/g6`), material choice, heat treatment, whether a dimension chain closes,
whether the part is manufacturable. A `pass` means the file survives being read — not that the
drawing can go to a shop.

## Install

```bash
pip install cad-deliver-mcp          # CLI, with ezdxf and PyMuPDF
pip install "cad-deliver-mcp[mcp]"   # adds the MCP server
```

`ezdxf` and `pymupdf` are default dependencies rather than extras on purpose: without
them every DXF and every PDF becomes `UNKNOWN`, and a checker that can only say
"could not judge" is not worth installing.

## Development

```bash
pip install -e ".[dev]"

python tests/test_layering.py       # geometry/ and rules/ import no CAD library
python tests/test_geometry.py
python tests/test_parsers.py
python tests/test_topology.py       # closure: flag-off rings, tolerance, layer filtering
python tests/test_rules.py          # 22 cases, pure ParsedDrawing
python tests/test_server.py         # 9 cases: stage, verify, commit and every refusal
python tests/test_legacy_compat.py  # exit codes 0/1/2 across profiles
```

`tests/golden_compare.py` compared this package against the frozen legacy implementation field by
field over 12 fixtures and printed `PARITY OK`. The baseline has since been deleted — two copies of
a delivery judgement is the drift the refactor set out to remove — so the script now reports
`baseline retired` unless `CAD_DELIVER_LEGACY` points at an older copy.

## Licence

MIT.