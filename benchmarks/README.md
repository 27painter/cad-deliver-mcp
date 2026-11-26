# Benchmark set

What this measures: whether a gatekeeper can tell a deliverable drawing from one
that merely opens. It is not a test of CAD parsing accuracy — it is a test of
whether the checks are worth running.

## Quick start

```bash
python benchmarks/generate_fixtures.py    # 15 compliant drawings
python benchmarks/mutate.py               # 20 defect-injected copies
python benchmarks/run_eval.py             # four arms, three CSV tables
```

`validate_real.py` is separate: it checks the real exports one at a time as you
drop them in, so a failing drawing is explained while you still remember what you
exported.

## Layout

```
fixtures/real/      15 SolidWorks/NX exports with a GB title block, anonymised
                    (yours to add; the directory ships empty)
fixtures/gen/       15 compliant drawings generated with ezdxf
fixtures/mutated/   20 mutated copies, 4 per defect class
results/            recall_by_defect.csv, false_positives.csv, latency.csv
tasks.json          the manifest every number above refers to
mutations.json      per-sample expected code and layer
```

`fixtures/gen/` and `fixtures/mutated/` are git-ignored: they are rebuilt
byte-for-byte by the scripts. `fixtures/real/`, `tasks.json`, `mutations.json`
and the result tables are committed — they cannot be regenerated and they are the
evidence.

## Dynamic scale

The evaluation adapts to how many real exports exist:

| `fixtures/real/` | tasks | compliant | mutated |
|---|---|---|---|
| empty | 35 | 15 generated | 20 |
| 15 files | 50 | 30 (15 generated + 15 real) | 20 |

There is no other switch. Drop the exports in, re-run `run_eval.py`, and the
tables extend. Until they exist, any recall figure describes generated data only
— which is why `false_positives.csv` reports `n=15` today and `n=30` once the real
set lands (and why its Clopper-Pearson bound is 18.1% rather than 9.5%).

## Defect classes

Each class targets one code, so recall can be attributed:

| class | n | injection | expected code | layer |
|---|---:|---|---|---|
| degenerate bbox | 4 | every entity kept, all coordinates collapsed to the origin | `E_BBOX_DEGENERATE` | geometry |
| open profile | 4 | one side of the outline removed | `E_PROFILE_OPEN` | standard |
| non-standard sheet | 4 | paper size → 400×280 mm | `E_SHEET_SIZE` | standard |
| missing title block | 4 | INSERT deleted, or a required ATTRIB blanked | `E_TITLE_BLOCK` / `E_TITLE_BLOCK_BLANK` | standard |
| wrong layer | 4 | DIMENSION onto the outline layer, or outline onto layer 0 | `E_DIM_ON_WRONG_LAYER` / `E_CONTOUR_ON_ZERO` | standard |

The title-block class deliberately **keeps the `比例 1:2` text on the sheet**. A
keyword-matching checker still sees a title block; the attribute-level rule does
not. That contrast is the reason this benchmark exists, and the `LEGACY` column
below is what makes it visible.

## Comparison arms

| arm | decision rule | role |
|---|---|---|
| G1 | no gate; always PASS | lower bound |
| G2 | file exists and is non-empty | weak baseline |
| G2.5 | `ezdxf` opens it, model space non-empty, `$INSUNITS != 0` | the competitor |
| G3 | this package, `GB_T_TIER1` | the system under test |
| LEGACY | this package, `LEGACY_COMPAT` (geometry checks only) | the previous behaviour |

`LEGACY` is not an arm in the paper's sense — it is the same code with the rule
layer switched off. It is measured because it is the honest answer to "was the
old checker really that bad?", and because it isolates what the rule layer adds.

## First run: 35 tasks

```
tasks: 35  (compliant 15 = gen 15 + real 0, mutated 20)

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
```

Reading it:

* **G1, G2 and G2.5 intercept nothing.** Static syntax checks cannot see content:
  a drawing with its sheet at 400×280 mm opens perfectly.
* **LEGACY intercepts 0/20.** The pre-existing checker catches nothing in any
  class. Note that this is conditional on how the bbox defect is injected: an
  earlier mutation deleted the model space, which tripped `drawing.entities` and
  credited the old checker with 4/20. The current mutation keeps all eight
  entities and only collapses their coordinates to the origin, so the entity
  count still passes and the interception is attributable to `geo.bbox_degenerate`
  alone. That is the difference between "an empty drawing" and "degenerate
  geometry", and it is what makes the row honest.
* **G3 intercepts 20/20**, and `G3_exact` in the CSV is also 20/20: it names the
  injected code each time, not just "something is wrong".

False positives and latency:

```
| arm           | n  | FP | rate  | CP 95% upper |
|---------------|----|----|-------|--------------|
| G1            | 15 |  0 | 0.0%  | 18.1%        |
| G2            | 15 |  0 | 0.0%  | 18.1%        |
| G2.5          | 15 |  0 | 0.0%  | 18.1%        |
| G3            | 15 |  0 | 0.0%  | 18.1%        |
| LEGACY_COMPAT | 15 |  0 | 0.0%  | 18.1%        |

| arm           | n  | p50 (ms) | p95 (ms) |
|---------------|----|---------:|---------:|
| G1            | 35 |    0.002 |    0.002 |
| G2            | 35 |    0.196 |    0.249 |
| G2.5          | 35 |   10.154 |   44.595 |
| G3            | 35 |   12.453 |   49.303 |
| LEGACY_COMPAT | 35 |   11.765 |   21.911 |
```

The rule layer costs about **2.3 ms at the median** over G2.5 — parsing dominates,
and five rules are nearly free on top of it. The p95 gap is wider because the
large sheets (A0) parse slower and have more entities to classify.

## Reporting rules

* A defect sample counts as **intercepted** when the verdict is not `PASS`. `FAIL`
  and `UNKNOWN` both count, but the two are never merged in the tables.
* A compliant sample counts as a **false positive** when the verdict is not `PASS`.
* Never report a bare "0%" for false positives. Report `k/n` with the exact
  Clopper-Pearson 95% one-sided upper bound, computed in `run_eval.py` from
  `math.comb` — no scipy dependency, so the number is reproducible anywhere.

## Current gaps

`fixtures/real/` holds one exported sample (`part_001.dxf`) while the remaining
fourteen are blocked on the issues below. Until they land, every recall figure
describes generated data only, and the false-positive bound stays at 18.1%
(n=15) instead of 9.5% (n=30).

The export path itself works — `scripts/batch_export_sw.py` drives SolidWorks
2025 through COM and produces a real DXF (mm units, first-angle three-view,
model dimensions, geometry in model space). What it cannot fix from code:

**Configuration SolidWorks exposes only in its UI.** The DXF writer has no COM
switch for layer mapping or for exporting the sheet format; everything lands on
layer 0 and the paper space stays empty, which trips `E_CONTOUR_ON_ZERO`,
`E_DIM_ON_WRONG_LAYER` and `E_TITLE_BLOCK`. Tools > Options > Export > DXF/DWG
covers both, plus a template whose title block is an attributed block.

**A rule whose precondition the artefact does not meet.** `gb.closed_profile`
assumes one drawing is one closed contour. A three-view drawing is made of open
segments — sixteen dangling ends is what it *is*, not a defect. That rule
therefore fires on 100% of real engineering drawings, structurally, and no amount
of tuning changes it. The same argument applies to `gb.sheet_size`, which also
judges the empty `Model` layout whose paper size is SolidWorks' Letter default.

Both are tracked as design questions rather than bugs: a rule with an unmet
precondition should abstain (`UNKNOWN`) instead of failing, which is the same
principle that produced the three verdicts in the first place.