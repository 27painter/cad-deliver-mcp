# Vision-language baseline: measured

Run over all 65 renders with `qwen3-vl-plus` through an OpenAI-compatible gateway
(`VLM_BASE` / `VLM_KEY` / `VLM_MODEL` in the environment; the key never enters this
repository).

## Headline

```
refused         19/20  (95%)      a defect sample where the model said "not compliant"
reason matched  11/20  (55%)      ... and the stated reason names the injected defect
false positives 17/30  (57%)      compliant samples the model called non-compliant
```

**Two numbers, not one.** 95% is what a "did it refuse" metric would report. It is nearly
double what the model actually achieved, because the model refuses almost everything: it
refused 17 of the 30 compliant drawings too. Reading each finding and asking whether it
names the thing that was broken gives 55%.

This is the methodological point of the baseline. Refusal rate is cheap to measure and
easy to over-read; it rewards a model that says no. Any evaluation of a visual reviewer
that reports only rejection is reporting a threshold, not a capability.

## What vision can and cannot see

| defect class | refused | **reason matched** | what the model actually said |
|---|---:|---:|---|
| `E_BBOX_DEGENERATE` | 4/4 | **4/4** | "no geometry, lines, or dimensions are present" — one even noted "one red dot are visible" |
| `E_PROFILE_OPEN` | 4/4 | **3/4** | "the outline is open: the horizontal base line ends short of the vertical right line, leaving a gap" |
| `E_TITLE_BLOCK` | 2/2 | **2/2** | "no ... complete title block is present" |
| `E_TITLE_BLOCK_BLANK` | 2/2 | **2/2** | "no visible title block fields filled, only 图名 text present" |
| `E_SHEET_SIZE` | 3/4 | **0/4** | reports A3 as if correct, or blames the title block; one passes the drawing outright |
| `E_DIM_ON_WRONG_LAYER` | 2/2 | **0/2** | blames the title block or missing dimensions; never mentions a layer |
| `E_CONTOUR_ON_ZERO` | 2/2 | **0/2** | "the image is cropped", "no line colours are visible (monochrome)" |

**The split is not random.** Every geometric defect was found; no attribute defect was.

That is exactly what the renders predict, and it is the same conclusion the file-level
analysis reached from the other side:

* a part that is not drawn is a *picture* fact — it is missing from the image;
* a layer name is a *symbolic* fact — `E_CONTOUR_ON_ZERO` moves the outline to layer `0`,
  which plots at colour 7, the colour the outline layer already used. The rendering is
  unchanged. Measured directly: `mut_19_contour_on_zero.png` has 18 chromatic pixels out
  of 18 919 non-white ones, and the compliant `PART-002.png` has 19 out of 22 159. **The
  two images are indistinguishable in colour.**

So the model was not wrong to call `mut_19` monochrome. It was wrong to treat that as a
finding about the drawing. It refused, and the reason it gave was about the image.

## Why the false-positive rate is the interesting number

The model refused 17 of 30 compliant drawings, and the reason is consistent: it reports
that it cannot see something and treats "cannot see" as "not compliant".

> "no visible dimensions or line weights to assess layers or dimension consistency"
> "title block fields are present but mostly blank"
> "line types are not distinguishable by colour/weight"

Two of those complaints are artefacts of this render: dimension values are not drawn at
all (see the limitation below), and most entities plot near-grey because their layer
colour is 7. The third is the model failing to connect labels to values that sit 36 mm
apart, which is normal title-block layout.

**But the behaviour generalises beyond these renders.** A reviewer that only looks has one
answer for missing information: reject. The rule layer has three — pass, fail, and
*unknown* — and uses the third when a precondition does not hold. That difference is worth
more than any single recall figure.

## Against the rule layer, same 20 samples

| | rule layer (`GB_T_TIER1`) | vision model |
|---|---|---|
| rejected | 20/20 | 19/20 |
| **reason/eCode correct** | **20/20** (exact machine code) | **11/20** |
| false positives | **0/30** | **17/30** |
| machine-readable verdict | yes, per-rule code + evidence | no; prose |

The rule layer is not merely more accurate. It produces a code, a coordinate and a fix
instruction; the model produces a paragraph that, in nine of twenty cases, describes
something other than the defect.

## Reproduce

```bash
# export VLM_BASE, VLM_KEY, VLM_MODEL first
python benchmarks/eval_vlm.py        # 65 calls, writes results/baseline_vlm.csv
python benchmarks/score_vlm.py       # reason-matching, writes baseline_vlm_scored.csv
```

`score_vlm.py` carries the twenty reason verdicts as a table with the phrase each rests
on, so the judgement is auditable rather than asserted. Disagree with one and the numbers
move — which is the point of writing them down.

## Known limitation of the render

Dimension **values** are not drawn. ezdxf generates them internally and `TextPolicy.IGNORE`
suppresses them along with every Chinese string; with text enabled the values return but so
do tofu boxes over all the Chinese labels. The trade went in favour of readable Chinese.

Consequence: the prompt's fifth question — do the printed values agree with the geometry —
cannot be answered from these images. Every model reported on it anyway. `dims_ok` is
therefore a measure of how models handle an unanswerable question, not of dimension
consistency, and it should not be read as the latter.

This limitation also inflates the false-positive rate: "no visible dimension values" is
one of the model's standing complaints. Fixing the render would move that number. It would
not change the geometric-versus-attribute split, which is the actual result.

## Three render bugs that had to be fixed first

Recorded because they were invisible until the images could be looked at, and because the
first VLM run — 62 of 65 refused, including all 15 compliant generated drawings — was
measuring those bugs, not the model.

1. **Paper space was never drawn.** Geometry lives in model space, the frame and title
   block live in the paper-space layout. Rendering `doc.modelspace()` alone put every
   drawing on the sheet with no title block.
2. **Drawing both spaces duplicated the part.** The layout's VIEWPORT already renders model
   content; `PART-002.DXF` has 7 entities in Model and 9 in 布局1, and drawing both
   superimposed two parts.
3. **A layout without a VIEWPORT showed nothing but its frame.** The ezdxf-generated
   drawings have no viewport, so a layout-only render was an empty sheet with a caption.
   `gen_01` came out blank and the model correctly reported a blank sheet — a rendering
   bug read back as a finding.

The renderer now draws the layout always, and model space additionally only when no
VIEWPORT exists to have drawn it. Chinese is drawn by matplotlib (`TextPolicy.IGNORE` in
ezdxf, every text entity placed by us) after ezdxf's font manager refused every CJK
substitution and logged `cannot open font 'mstmc.ttf'`.
