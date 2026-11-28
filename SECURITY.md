# Security policy

## Supported versions

Security fixes are provided for the current `1.x` release line. `0.x` releases are
no longer maintained.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository:

https://github.com/27painter/cad-deliver-mcp/security/advisories/new

Do not open a public issue for a vulnerability. Include the affected version,
platform, the input file or profile that triggers it, reproduction steps, and the
observed versus expected verdict.

## Trust and execution model

`cad-deliver-mcp` is an independent open-source project. It is not affiliated
with, endorsed by, or supported by Autodesk or Dassault Systèmes.

### What the package does with your files

- **Reads only the paths you pass.** Parsing happens in `parsers/`, using `ezdxf`
  for DXF and PyMuPDF for PDF. Nothing outside the given paths and the staging
  directory is opened.
- **Staging lives outside your delivery folder.** Files are copied to
  `%TEMP%/cad-deliver-staging/<id>/` (`CAD_DELIVER_STAGING` overrides this) and
  are not written to the target directory until `deliver_commit`.
- **Commit is atomic and refuses to overwrite.** Each file is written to
  `<target_dir>/<name>.partial`, flushed, then promoted with `os.replace`.
  An existing file is never replaced unless `overwrite=True` is passed
  explicitly.
- **No network access.** The gatekeeper is offline by design: no telemetry, no
  update check, no remote rule fetch. Rules and the standards table ship inside
  the wheel (`standards.json`, `rules/gb/*.json`).
- **The one exception is opt-in and outside the package.** The benchmark scripts
  under `scripts/` and `benchmarks/eval_vlm.py` call a vision-language model when
  `VLM_BASE` / `VLM_KEY` / `VLM_MODEL` are set. That path is for reproducing the
  paper's baseline, not for gating a delivery.

### What it explicitly is not

**It is not a sandbox.** The state machine makes the gap between *verified* and
*released* observable, and catches a file edited after verification via SHA-256.
It does not stop an agent from staging the same file again after editing it and
obtaining a clean `VERIFIED`. The audit store keeps `attempts` and `history` so
re-entry loops stay visible — a protocol discipline, not a security boundary.

**It does not judge design intent.** Tolerances and fits, materials, heat
treatment, tolerance-stack closure and manufacturability are out of scope. A
`PASS` certifies structural and drafting-standard integrity, not engineering
sign-off.

### Threat model boundaries

- Untrusted DXF/PDF input is parsed by third-party libraries (`ezdxf`, `PyMuPDF`).
  A memory-safety or parser bug in either is their advisory, not this project's;
  report it upstream as well.
- `stdout` is the MCP protocol channel. `server.py` redirects `print` and routes
  logging to `stderr` at import time so diagnostics cannot corrupt a JSON-RPC
  frame. Anything that writes to `stdout` after that point is a bug worth
  reporting.
- The `scripts/` directory drives real CAD applications through COM
  (`SolidWorks.Interop`, AutoCAD `Document.Export`). Those scripts are research
  tooling: they start installed applications, and they are not installed by the
  wheel.
