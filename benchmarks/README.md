# Benchmark set

The task set that measures this gatekeeper. It is **not populated yet** — this file describes
what goes where, so the numbers in a paper or a release note can be traced to a fixture.

## Layout

```
fixtures/real/    15 drawings exported from SolidWorks / NX with a GB title block, anonymised
fixtures/gen/     15 compliant drawings generated with ezdxf (A0–A4 boundaries)
fixtures/defective/ 20 mutated copies of the above, 4 per defect class (generated, not checked in)
results/          run_eval.py output: per-class recall, false-positive rate, latency
```

`fixtures/defective/` and `results/` are produced by the scripts and stay out of git
(see `.gitignore`), so a clone always regenerates them from the same inputs rather than
inheriting a stale copy.

## Defect classes

Each class targets one rule, so a recall figure can be attributed:

| class | injection | expected to fire |
|---|---|---|
| degenerate bbox | coordinates collapse to zero or a line | `step.bbox` |
| open outline | drop one side of a closed polygon | `E_PROFILE_OPEN` |
| non-standard sheet | paper size → 400×280 mm | `E_SHEET_SIZE` |
| missing title block | delete the frame block from paper space | `E_TITLE_BLOCK` / `E_TITLE_BLOCK_BLANK` |
| entity on the wrong layer | move a DIMENSION to the outline layer | `E_DIM_ON_WRONG_LAYER` |

## Comparison groups

| group | decision rule | role |
|---|---|---|
| G1 | no gate; the model reports completion | lower bound |
| G2 | file exists and exceeds a size threshold | weak baseline |
| G2.5 | ezdxf opens it, entities non-empty, units ≠ 0 | the real competitor |
| G3 | this package | upper bound |

G2.5 is the group that matters. Comparing only against G1 and G2 invites the objection that the
baseline was never credible.

## Reporting

- recall per defect class and overall, split by rule layer (`geometry` / `standard`)
- false positives over the 30 compliant fixtures, reported as
  `0/30, Clopper-Pearson 95% one-sided upper bound 9.5%` — never a bare "0%"
- median and p95 latency for one `verify` call

## Status

Nothing here has been run. The 15 real fixtures do not exist yet, so any recall number
published before they arrive is a number about generated data only.