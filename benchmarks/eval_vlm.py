"""Run a vision-language model over the rendered drawings, or prepare to.

The question this baseline answers: can a model that only *looks* at the picture reach
the verdict the rule layer reaches from the file? That matters because most published
CAD-agent work inspects screenshots, and because a human reviewer works from the sheet.

Two modes:

  * **With a key** — one of `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`
    present — every render is sent with the same prompt and the answers are collected
    into `benchmarks/results/baseline_vlm.csv`.
  * **Without a key** — `benchmarks/vlm_requests.jsonl` is written: one line per image
    with the prompt, the expected code and the image path, ready for any client. Run
    the answers back through `scripts/parse_vlm_results.py` to get the same CSV.

The prompt asks for a verdict *and* coordinates, because a bare "looks wrong" cannot be
scored against an injected defect.

    python benchmarks/eval_vlm.py                 # auto-detect
    python benchmarks/eval_vlm.py --provider gemini
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDERS = ROOT / "benchmarks" / "renders"
RESULTS = ROOT / "benchmarks" / "results"
FIXTURES = ROOT / "benchmarks" / "fixtures"
MUTATIONS = ROOT / "benchmarks" / "mutations.json"

PROMPT = """You are a mechanical drawing compliance reviewer. Look at the image of a
GB/T engineering drawing and answer five questions. Be concrete; if you cannot tell,
say so rather than guessing.

1. SHEET: which ISO 216 / GB/T 14689 size is the sheet (A4, A3, A2, A1, A0), and is it
   landscape or portrait? Judge from the drawn border, not from the image size.
2. LAYERS: can you identify distinct line types by colour or weight — a visible outline,
   centre lines, dimensions, a frame? Name the colours you see for each.
3. TITLE BLOCK: is there a title block in the lower right? Are the fields 图名 / 图号 /
   比例 filled in, or blank?
4. OUTLINE CLOSURE: is the visible outline a closed contour, or does it have a gap?
   If there is a gap, give the approximate coordinates of the two loose ends in
   millimetres from the lower-left corner of the sheet.
5. DIMENSIONS: do the printed dimension values look consistent with the drawn geometry?
   If a value looks wrong, name the dimension and both numbers.

Answer with a single JSON object and nothing else:
{"sheet":"A3","sheet_ok":true,"layers_ok":true,"title_block_ok":true,
 "closed_ok":true,"dims_ok":true,"finding":"one sentence","loose_ends":[[0,0],[0,0]],
 "confidence":"high|medium|low"}"""


def expected_map() -> dict[str, dict]:
    """Per-sample expectation, keyed by render stem."""
    mapping: dict[str, dict] = {}
    if MUTATIONS.is_file():
        data = json.loads(MUTATIONS.read_text(encoding="utf-8"))
        records = data["records"] if isinstance(data, dict) else data
        for record in records:
            stem = Path(record["path"]).stem
            mapping[stem] = {
                "group": "mutated",
                "expected_code": record.get("expected_code", ""),
                "defect_class": record.get("label", ""),
                "should_be_clean": False,
            }
    for group in ("real", "real_sw", "gen"):
        folder = FIXTURES / group
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.suffix.lower() == ".dxf":
                mapping.setdefault(
                    path.stem,
                    {
                        "group": group,
                        "expected_code": "",
                        "defect_class": "",
                        "should_be_clean": group in ("real", "gen"),
                    },
                )
    return mapping


def collect_images(group: str | None) -> list[Path]:
    files: list[Path] = []
    for folder in sorted(RENDERS.iterdir()) if RENDERS.is_dir() else []:
        if not folder.is_dir():
            continue
        if group and folder.name != group:
            continue
        files.extend(sorted(folder.glob("*.png")))
    return files


def write_requests(images: list[Path], expected: dict[str, dict]) -> Path:
    out = ROOT / "benchmarks" / "vlm_requests.jsonl"
    with open(out, "w", encoding="utf-8") as handle:
        for image in images:
            meta = expected.get(image.stem, {})
            handle.write(
                json.dumps(
                    {
                        "image": str(image.relative_to(ROOT)).replace("\\", "/"),
                        "group": meta.get("group", image.parent.name),
                        "expected_code": meta.get("expected_code", ""),
                        "defect_class": meta.get("defect_class", ""),
                        "should_be_clean": meta.get("should_be_clean", None),
                        "prompt": PROMPT,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return out


def detect_provider() -> tuple[str, str] | None:
    """Return (provider, model), or None when no credentials are configured.

    `VLM_BASE` + `VLM_KEY` takes precedence: any OpenAI-compatible gateway works, and
    keeping the endpoint in the environment rather than in this file means a key never
    reaches the repository.
    """
    if os.environ.get("VLM_BASE") and os.environ.get("VLM_KEY"):
        return "custom", os.environ.get("VLM_MODEL", "qwen3-vl-plus")
    for name, env, model in (
        ("openai", "OPENAI_API_KEY", "gpt-4o"),
        ("gemini", "GEMINI_API_KEY", "gemini-2.0-flash"),
        ("dashscope", "DASHSCOPE_API_KEY", "qwen-vl-max"),
    ):
        key = os.environ.get(env)
        if key:
            return name, model
    return None


def call_openai_like(image: Path, model: str) -> str:
    """Any OpenAI-compatible endpoint; the base URL comes from VLM_BASE or a default."""
    import urllib.request

    if os.environ.get("VLM_BASE") and os.environ.get("VLM_KEY"):
        key = os.environ["VLM_KEY"]
        base = os.environ["VLM_BASE"].rstrip("/")
    else:
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY", "")
        base = (
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
            if os.environ.get("DASHSCOPE_API_KEY") and not os.environ.get("OPENAI_API_KEY")
            else "https://api.openai.com/v1"
        )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(image.read_bytes()).decode()
                        },
                    },
                ],
            }
        ],
        "max_tokens": 800,
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read())
    return body["choices"][0]["message"]["content"]


def call_gemini(image: Path, model: str) -> str:
    import urllib.request

    key = os.environ.get("GEMINI_API_KEY", "")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(image.read_bytes()).decode(),
                        }
                    },
                ]
            }
        ]
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read())
    return body["candidates"][0]["content"]["parts"][0]["text"]


def parse_answer(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {"raw": text, "parse_error": True}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"raw": text, "parse_error": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", default=None)
    parser.add_argument("--provider", default=None, choices=["openai", "gemini", "dashscope"])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    images = collect_images(args.group)
    if args.limit:
        images = images[: args.limit]
    if not images:
        print("no renders found; run scripts/render_dxf_png.py first")
        return 1

    expected = expected_map()
    detected = detect_provider()
    print(f"images   : {len(images)}")
    print(f"provider : {detected[0] + ' / ' + detected[1] if detected else 'none configured'}")

    if not detected:
        out = write_requests(images, expected)
        print()
        print("No multimodal API key found in the environment.")
        print(f"  wrote {out.relative_to(ROOT)}  ({len(images)} request(s))")
        print()
        print("Next, either:")
        print("  1. export OPENAI_API_KEY / GEMINI_API_KEY / DASHSCOPE_API_KEY and re-run")
        print("     this script - it will call the model and write the CSV; or")
        print("  2. send each request to any vision model yourself, save the answers")
        print("     one JSON object per line to benchmarks/vlm_answers.jsonl, then run")
        print("     python scripts/parse_vlm_results.py")
        return 0

    provider, model = detected
    rows = []
    for index, image in enumerate(images, start=1):
        meta = expected.get(image.stem, {})
        try:
            raw = (
                call_gemini(image, model)
                if provider == "gemini"
                else call_openai_like(image, model)
            )
            answer = parse_answer(raw)
        except Exception as exc:  # noqa: BLE001
            answer = {"error": f"{type(exc).__name__}: {exc}"}
        passed = all(
            answer.get(key, False)
            for key in ("sheet_ok", "layers_ok", "title_block_ok", "closed_ok", "dims_ok")
        )
        rows.append(
            {
                "sample": image.stem,
                "group": meta.get("group", image.parent.name),
                "expected_code": meta.get("expected_code", ""),
                "should_be_clean": meta.get("should_be_clean", ""),
                "vlm_rejects": "" if "error" in answer else ("no" if passed else "yes"),
                "vlm_sheet": answer.get("sheet", ""),
                "vlm_finding": answer.get("finding", answer.get("error", "")),
                "vlm_confidence": answer.get("confidence", ""),
                "raw": json.dumps(answer, ensure_ascii=False)[:400],
            }
        )
        print(f"  {index:>3}/{len(images)}  {image.stem:<32} {'reject' if rows[-1]['vlm_rejects'] == 'yes' else 'accept'}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "baseline_vlm.csv"
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print()
    print(f"written: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())