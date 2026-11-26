# VLM baseline — prepared, not yet run

The visual baseline is built but unscored: this machine has no multimodal API key, so
`results/baseline_vlm.csv` does not exist. Nothing below is a guess.

## What is ready

| artefact | path | state |
|---|---|---|
| renders | `benchmarks/renders/{real,real_sw,mutated,gen}/*.png` | 65 images, 150 dpi |
| request manifest | `benchmarks/vlm_requests.jsonl` | 65 requests, one JSON per line |
| prompt | see `prompt` in each request | fixed, versioned with the repo |
| answer parser | `scripts/parse_vlm_results.py` | writes the same CSV as online mode |
| online runner | `benchmarks/eval_vlm.py` | calls the API when a key is present |

Rendering is deterministic: `scripts/render_dxf_png.py` draws layer colours, line
weights at 1.4x, and the sheet border taken from each layout's declared paper size, so
a wrong sheet reads as a wrong sheet in the picture.

## Two ways to finish it

**A. Give it a key.** Export one of `OPENAI_API_KEY`, `GEMINI_API_KEY` or
`DASHSCOPE_API_KEY`, then:

```bash
python benchmarks/eval_vlm.py            # calls the model, writes results/baseline_vlm.csv
```

**B. Run it anywhere, then import.** Send each line of `vlm_requests.jsonl` to any
vision model (a chat UI works), and save the replies as one JSON object per line in
`benchmarks/vlm_answers.jsonl`:

```json
{"image": "benchmarks/renders/mutated/mut_01_bbox_point.png", "answer": {"sheet":"A4","sheet_ok":true,"layers_ok":false,"title_block_ok":true,"closed_ok":false,"dims_ok":true,"finding":"outline collapsed to a point","confidence":"high"}}
```

Then:

```bash
python scripts/parse_vlm_results.py
```

## What the prompt asks for, and why

Five judgements — sheet size, layer separation, title-block fields, outline closure,
dimension consistency — and, for the closure case, the coordinates of the loose ends.
A bare "looks wrong" cannot be scored against an injected defect; coordinates can.

The prompt is in English while the drawing is Chinese-titled. That is deliberate: the
attributes 图名 / 图号 / 比例 are read as glyphs rather than inferred from context, which
is the harder and more informative case.

## What a result would mean

The comparison of interest is not "did the model pass" but **which defect classes are
visible at all**. From the rule side we already know the answer for two of them:

* `E_BBOX_DEGENERATE` collapses every coordinate to the origin. The render shows an
  almost empty sheet — 4 distinct colours, 0.2% ink against 214 colours and 0.4% for a
  healthy drawing. A vision model should catch this one.
* `E_CONTOUR_ON_ZERO` moves entities to layer `0`, which changes the colour they are
  drawn in. Whether a model reads a colour change as a *defect* rather than a style
  choice is exactly the open question, and it is the one worth reporting.

`E_SHEET_SIZE` should also be visible, but only if the model measures the border rather
than trusting the image dimensions — the renders are all saved at 150 dpi, so image
size carries no information about paper size.

## Why not fake a row

A baseline row invented to fill the table would contaminate every comparison that cites
it. An explicit "prepared, not run" is a weaker claim and a true one.