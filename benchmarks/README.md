# Benchmark set

What this measures: whether a gatekeeper can tell a deliverable drawing from one
that merely opens. It is not a test of CAD parsing accuracy — it is a test of
whether the checks are worth running.

## Quick start

```bash
python scripts/gen_acad_fixtures.py       # 15 AutoCAD exports (A4/A3/A2)
python benchmarks/generate_fixtures.py    # 15 generated compliant drawings
python benchmarks/mutate.py               # 20 defect-injected copies
python benchmarks/run_eval.py             # five arms, four CSV tables
```

`validate_real.py` is separate and narrower: it runs `GB_T_TIER1` over
`fixtures/real/` only and exits non-zero unless every export passes. `run_eval.py`
is the broad one — it also reports the SolidWorks contrast, which is *expected* to
be UNKNOWN rather than PASS.

## Layout

```
fixtures/real/      15 AutoCAD 2025 exports, Document.Export to DXF;
                    A4 x5, A3 x7, A2 x3; scales 1:1 / 1:2 / 2:1;
                    fifteen distinct part geometries
fixtures/real_sw/   15 SolidWorks 2025 exports of the same parts - the
                    cross-ecosystem contrast group, deliberately NOT in the
                    compliant set
fixtures/gen/       15 compliant drawings generated with ezdxf
fixtures/mutated/   20 mutated copies, one defect each, 10 from real + 10 from gen
results/            recall_by_defect.csv, false_positives.csv, latency.csv,
                    cross_ecosystem.csv
tasks.json          the manifest every number above refers to
mutations.json      per-sample expected code, layer and profile
```

`fixtures/gen/` and `fixtures/mutated/` are git-ignored: they are rebuilt
byte-for-byte by the scripts. `fixtures/real/`, `fixtures/real_sw/`, `tasks.json`,
`mutations.json` and the result tables are committed — they cannot be regenerated
identically, and they are the evidence.

**No exported DXF is post-processed.** What lands in `fixtures/real*/` is what the
CAD application wrote. That constraint is what makes the cross-ecosystem numbers
below mean anything.

## Scale: 50 tasks

The set is complete and fixed at 50:

| source | n | role |
|---|---:|---|
| `fixtures/real` (AutoCAD) | 15 | compliant |
| `fixtures/gen` | 15 | compliant |
| `fixtures/mutated` | 20 | defective, 10 from real + 10 from gen |
| `fixtures/real_sw` (SolidWorks) | 15 | cross-ecosystem contrast, **not** in the compliant set |

`run_eval.py` still adapts if `fixtures/real/` is empty (it falls back to 35 and
says so), but that path exists only for a fresh checkout before the exporter has
run. Every number in the tables below is the 50-task run.

## Defect classes

Six classes, 20 injected defects, each with an expected machine code:

| class | injected defect | expected code |
|---|---|---|
| degenerate bbox | every coordinate collapsed to the origin | `E_BBOX_DEGENERATE` |
| dimension on wrong layer | one `DIMENSION` moved onto the outline layer | `E_DIM_ON_WRONG_LAYER` |
| missing title block | the title block `INSERT` deleted | `E_TITLE_BLOCK` |
| non-standard sheet | paper size set to 400x280 mm | `E_SHEET_SIZE` |
| open profile | one vertex dropped from a closed polyline | `E_PROFILE_OPEN` |
| outline on layer 0 | outline entities moved to layer `0` | `E_CONTOUR_ON_ZERO` |

Each mutation is verified on write: the file must fail the gate, and the gate must
name the expected code. `mutate.py` reports `injected / exact / intercepted` and
refuses to write a manifest when they disagree.

## Comparison arms

Cumulative, so the difference between adjacent arms is one layer of checking:

| arm | what it does |
|---|---|
| G1 | header only — is this a readable DXF |
| G2 | + geometry — extents, entity counts |
| G2.5 | + outline closure, the pre-existing `dsh-sw-cad` check set |
| G3 | + the full rule set (`GB_T_TIER1` plus `PROFILE_CLOSURE` routing) |
| LEGACY_COMPAT | the published `delivery.json` contract, no GB rule at all |

G2.5 is the arm that matters. Comparing only against G1 and G2 invites the
objection that the baseline was never credible; G2.5 is what a competent engineer
would write in an afternoon without a rule layer.

## The 50-task run

```
tasks: 50  (compliant 30 = gen 15 + real 15, mutated 20)

| defect class              | layer    |  n | G1   | G2   | G2.5 | G3    | LEGACY |
|---------------------------|----------|---:|------|------|------|-------|--------|
| degenerate bbox           | geometry |  4 | 0/4  | 0/4  | 0/4  | 4/4   | 0/4    |
| dimension on wrong layer  | standard |  2 | 0/2  | 0/2  | 0/2  | 2/2   | 0/2    |
| missing title block       | standard |  4 | 0/4  | 0/4  | 0/4  | 4/4   | 0/4    |
| non-standard sheet        | standard |  4 | 0/4  | 0/4  | 0/4  | 4/4   | 0/4    |
| open profile              | standard |  4 | 0/4  | 0/4  | 0/4  | 4/4   | 0/4    |
| outline on layer 0        | standard |  2 | 0/2  | 0/2  | 0/2  | 2/2   | 0/2    |
| ALL (geometry)            | geometry |  4 | 0/4  | 0/4  | 0/4  | 4/4   | 0/4    |
| ALL (standard)            | standard | 16 | 0/16 | 0/16 | 0/16 | 16/16 | 0/16   |
| ALL                       | both     | 20 | 0/20 | 0/20 | 0/20 | 20/20 | 0/20   |

| arm           |  n | FP | rate | CP 95% upper |
|---------------|---:|---:|-----:|-------------:|
| G1            | 30 |  0 | 0.0% |         9.5% |
| G2            | 30 |  0 | 0.0% |         9.5% |
| G2.5          | 30 |  0 | 0.0% |         9.5% |
| G3            | 30 |  0 | 0.0% |         9.5% |
| LEGACY_COMPAT | 30 |  0 | 0.0% |         9.5% |

| arm           |  n | p50 (ms) | p95 (ms) |
|---------------|---:|---------:|---------:|
| G1            | 50 |    0.002 |    0.002 |
| G2            | 50 |    0.197 |    0.370 |
| G2.5          | 50 |   10.185 |   47.252 |
| G3            | 50 |   12.653 |   51.976 |
| LEGACY_COMPAT | 50 |   11.775 |   34.342 |
```

Reading it:

* **G1, G2 and G2.5 intercept nothing at the standard level.** Static syntax checks
  cannot see content: a drawing with its sheet at 400x280 mm opens perfectly.
* **LEGACY intercepts 0/20.** This is conditional on how the bbox defect is
  injected. An earlier mutation deleted the model space, which tripped
  `drawing.entities` and credited the old checker with 4/20. The current mutation
  keeps every entity and only collapses their coordinates, so the entity count still
  passes and the interception is attributable to `geo.bbox_degenerate` alone. That
  is the difference between "an empty drawing" and "degenerate geometry", and it is
  what makes the row honest.
* **G3 intercepts 20/20**, and `G3_exact` in the CSV is also 20/20: it names the
  injected code each time, not just "something is wrong".
* **The rule layer costs about 2.5 ms at the median over G2.5.** Parsing dominates;
  six rules are nearly free on top of it. The p95 gap is wider because the A2 sheets
  parse slower and carry more entities to classify.

### Cross-ecosystem contrast

`fixtures/real_sw/` holds the same fifteen parts exported by SolidWorks. Same gate,
same rules:

```
| source            | CAD system | n  | PASS | FAIL | UNKNOWN |
|-------------------|------------|----|------|------|---------|
| fixtures/real     | AutoCAD    | 15 |   15 |    0 |       0 |
| fixtures/real_sw  | SolidWorks | 15 |    0 |    2 |      13 |
```

The two FAILs are real defects, kept on purpose: `part-006` exported no dimensions
at all, and `part-013` prints one dimension at 1.33x its measured length — a single
reading cannot establish a scale factor, so it is reported rather than excused.

The thirteen UNKNOWNs are the finding, not a defect in either side. Those DXFs carry
no sheet format, no layer structure and no sheet size, so `gb.title_block`,
`gb.layer_taxonomy` and `gb.sheet_size` abstain — and `CRITICAL_RULES` turns an
abstention on any of them into `UNKNOWN` instead of `PASS`. Five compliance
dimensions, two checked, is not a pass.

`gb.dim_text` does recognise a scaled sheet: when every overridden dimension reads
the same multiple of the measured length (7x on eight of them), the view is scaled
and the text states model values. A hand-edited text is a one-off wrong number.

## Result tables and how to reproduce them

| file | what it answers | built by |
|---|---|---|
| `results/recall_by_defect.csv` | per defect class, which arm caught it and whether the code matched | `run_eval.py` |
| `results/false_positives.csv` | per arm, false positives on the 30 compliant samples with the CP 95% upper bound | `run_eval.py` |
| `results/latency.csv` | per arm p50/p95 in ms over all 50 tasks | `run_eval.py` |
| `results/cross_ecosystem.csv` | AutoCAD vs SolidWorks under the same gate | `run_eval.py` |
| `tasks.json` | the manifest: every sample, its kind, group, profile, expected code | `run_eval.py` |
| `mutations.json` | per mutation: expected code, expected layer, profile | `mutate.py` |

One chain rebuilds everything:

```bash
python scripts/gen_acad_fixtures.py       # 15 AutoCAD exports via COM, ~4 min
python scripts/batch_export_sw.py --input tmp_sw_parts \
       --output benchmarks/fixtures/real_sw   # SolidWorks contrast, ~15 min
python benchmarks/mutate.py               # 20 mutations, 10 real + 10 gen
python benchmarks/run_eval.py             # the four tables + tasks.json
python benchmarks/validate_real.py        # compliant set on its own
```

## Reporting rules

* A defect sample counts as **intercepted** when the verdict is not `PASS`. `FAIL`
  and `UNKNOWN` both count, but the two are never merged in the tables.
* A compliant sample counts as a **false positive** when the verdict is not `PASS`.
* Never report a bare "0%" for false positives. Report `k/n` with the exact
  Clopper-Pearson 95% one-sided upper bound, computed in `run_eval.py` from
  `math.comb` — no scipy dependency, so the number is reproducible anywhere.
* An `UNKNOWN` on a *contrast* sample is not a false positive and does not enter
  that denominator: the artefact lacks the information the rule needs, so the rule
  correctly declines to answer.