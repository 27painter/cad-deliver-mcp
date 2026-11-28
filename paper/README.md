# Paper sources

Manuscript accompanying this repository:

> **Abstention Is Not a Pass: Pre-Delivery Verification for LLM-Generated CAD Drawings**

Submitted to the ASME *Journal of Computing and Information Science in Engineering*.

## Build

Requires a LaTeX distribution with `pdflatex` and `bibtex` (TeX Live or MiKTeX).

```bash
cd paper
pdflatex main && bibtex main && pdflatex main && pdflatex main
pdflatex supplementary
```

Four passes for the main document: the first writes `.aux`, `bibtex` resolves the
13 references into `.bbl`, and the two later passes settle cross-references and
the `asmejour` float placement.

## What is committed, and what is not

| Committed | Not committed |
|---|---|
| `main.tex`, `supplementary.tex`, `references.bib` | `*.pdf` |
| `asmejour.cls`, `asmejour.bst`, `asmejour-style.css` | `*.aux`, `*.log`, `*.bbl`, `*.blg`, `*.out`, `*.toc` |

The class and bibliography style files are committed because the manuscript does
not compile without them, and the ASME template is not something a reader should
have to hunt down. The PDFs are not: a PDF in git silently goes stale and nobody
can tell which revision it describes. The release PDF is attached to the GitHub
release for the matching version.

## Every number is reproducible

Each experimental figure in the manuscript comes from a file in this repository:

| Claim | Source |
|---|---|
| 20/20 recall, 0/30 false positives | `benchmarks/results/recall_by_defect.csv`, `false_positives.csv` |
| 12.37 / 50.75 ms latency, 2.07 ms overhead | `benchmarks/results/latency.csv` |
| leave-one-out ablation | `benchmarks/results/ablation_loo.csv` |
| AutoCAD `.dws` baseline | `benchmarks/results/baseline_dws.csv` |
| vision-language baseline | `benchmarks/results/baseline_vlm_scored.csv` |
| cross-ecosystem verdicts | `benchmarks/results/cross_ecosystem.csv` |
| closed-loop repair | `benchmarks/results/complex_repair_results.csv` |
| 74 tests, 4,682 LOC | `python -m pytest -q`, `src/**/*.py` |

The pixel statistics quoted in §5.6 (1 098 / 18 919 and 1 150 / 22 159, at
chroma threshold `max(R,G,B) - min(R,G,B) > 30/255`) are recomputed directly from
`benchmarks/renders/mutated/mut_19_contour_on_zero.png` and
`benchmarks/renders/real/PART-002.png`.
