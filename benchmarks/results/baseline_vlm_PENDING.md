# VLM baseline — prepared, not yet scored

The visual baseline is built but unscored: this machine has no multimodal API key, so
`results/baseline_vlm.csv` does not exist. Nothing below is a guess.

Building the renders took three fixes that only became visible once the images could
actually be looked at, and one of them produced a prediction worth stating before any
model runs.

## What is ready

| artefact | path | state |
|---|---|---|
| renders | `benchmarks/renders/{real,real_sw,mutated,gen}/*.png` | 65 images, 150 dpi |
| request manifest | `benchmarks/vlm_requests.jsonl` | 65 requests, one JSON per line |
| prompt | see `prompt` in each request | fixed, versioned with the repo |
| answer parser | `scripts/parse_vlm_results.py` | writes the same CSV as online mode |
| online runner | `benchmarks/eval_vlm.py` | calls the API when a key is present |

## Three render bugs, and why they mattered

**1. Paper space was not drawn.** The first version rendered `doc.modelspace()` only.
In an AutoCAD engineering drawing the geometry lives in model space while the frame and
title block live in the paper-space layout, so every render had no title block at all —
and one of the five prompt questions is whether the title block fields are filled.

**2. Drawing both spaces duplicated the part.** The fix for (1) was to draw model space
*and* the layout, which superimposed every part twice: the layout's VIEWPORT already
renders the model content. `PART-002.DXF` has 7 entities in Model and 9 in 布局1, and
drawing both put two overlapping parts on one sheet. The renderer now draws exactly one
space — the layout when it carries anything, model space otherwise.

**3. Chinese rendered as tofu boxes.** The text style is `Standard` with `font='txt'`,
AutoCAD's SHX stroke font, which has no CJK glyphs. ezdxf's font manager refused every
substitution tried (`find_best_match` returned nothing for Microsoft YaHei, SimHei and
SimSun, and logged `cannot open font 'mstmc.ttf'` while scanning). The renderer now asks
ezdxf to draw geometry only (`TextPolicy.IGNORE`) and places every text entity itself
with matplotlib's CJK stack.

A fourth attempt — let ezdxf draw text normally and paint over the CJK strings — was
reverted. The white patch never lined up with the tofu boxes and 端盖 came out as 删盖.
Garbled text is worse than absent text, because it is still confidently wrong.

## What the renders show, and the prediction that follows

Looking at the images produced one conclusion that the file-level analysis had only
implied:

> **Two of the six defect classes are visually invisible.**

| defect class | visible in the render? | what the image shows |
|---|---|---|
| `E_BBOX_DEGENERATE` | **yes, unmistakably** | the frame and title block are intact, the part has vanished — one red dot at the origin |
| `E_CONTOUR_ON_ZERO` | **no** | layer `0` plots at colour 7, exactly the colour the outline layer uses; the drawing looks correct |
| `E_SHEET_SIZE` | yes, but only if measured | the border is drawn from the layout's declared paper size |
| `E_TITLE_BLOCK` | yes | the title block reference is absent from the sheet |
| `E_TITLE_BLOCK_BLANK` | yes | labels present, values empty |
| `E_PROFILE_OPEN` | probably | a gap in the outline, if the model looks closely |
| `E_DIM_ON_WRONG_LAYER` | maybe | a dimension drawn in the wrong colour |

`mut_01_bbox_point.png` and `PART-002.png` sit side by side as the extreme case: same
frame, same title block, same field layout, and in one of them the part is simply not
there.

`mut_19_contour_on_zero.png` is the opposite case and the more interesting one. The
outline has been moved to layer `0`, which plots at the same colour as the outline layer
it came from. **The drawing looks exactly like a correct one.** No amount of looking
finds it, because the information that distinguishes them is a layer name, and a layer
name is not a picture.

So the prediction to test is: **a vision model should recall the geometric defects and
miss the layer-topology ones**, landing somewhere around 3–4 of 6 classes. A model that
reports perfect recall on this set is either reading the DXF rather than the image, or
guessing.

## Two ways to finish it

**A. Give it a key.** Export one of `OPENAI_API_KEY`, `GEMINI_API_KEY` or
`DASHSCOPE_API_KEY`, then:

```bash
python benchmarks/eval_vlm.py            # calls the model, writes results/baseline_vlm.csv
```

**B. Run it anywhere, then import.** Send each line of `vlm_requests.jsonl` to any
vision model, and save the replies as one JSON object per line in
`benchmarks/vlm_answers.jsonl`:

```json
{"image": "benchmarks/renders/mutated/mut_01_bbox_point.png", "answer": {"sheet":"A4","sheet_ok":true,"layers_ok":false,"title_block_ok":true,"closed_ok":false,"dims_ok":true,"finding":"no part geometry on the sheet","confidence":"high"}}
```

Then:

```bash
python scripts/parse_vlm_results.py
```

## Known limitation of the render

Dimension **values** are not drawn. ezdxf generates them internally and `TextPolicy.IGNORE`
suppresses them along with every other string; when text was enabled they came back but
so did the tofu boxes over all the Chinese. The trade was made in favour of readable
Chinese.

Consequence: the prompt's fifth question — do the printed dimension values agree with the
geometry — **cannot be answered from these images**. A model that answers it anyway is
bluffing, and the CSV records `dims_ok` as whatever the model claims, which is itself a
useful signal about how models handle an unanswerable question.

Every other question is answerable: sheet size from the border, layer separation from
colour, title-block completeness from the fields, outline closure from the geometry.