"""Packaging metadata: the things PyPI rejects only at upload time.

`twine check` validates the README renders; it does **not** validate classifiers.
A classifier that is not on PyPI's list gets the whole upload rejected with a 400
after the build succeeded and every test passed — which is exactly what happened
with `Topic :: Scientific/Engineering :: CAD` (there is no CAD topic).

The classifier check needs the network. When it is unavailable the test says so
and passes, rather than making an offline build fail.
"""

from __future__ import annotations

import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CLASSIFIER_URL = "https://pypi.org/pypi?%3Aaction=list_classifiers"


def load() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def test_version_matches_the_package():
    """Two places state the version; they must not drift."""
    import cad_deliver

    declared = load()["project"]["version"]
    assert cad_deliver.__version__ == declared, (
        f"pyproject says {declared}, cad_deliver.__version__ says {cad_deliver.__version__}"
    )


def test_required_metadata_is_present():
    project = load()["project"]
    for field in ("name", "version", "description", "readme", "requires-python", "license"):
        assert project.get(field), f"project.{field} is missing"
    assert project["requires-python"].startswith(">="), project["requires-python"]
    scripts = project.get("scripts") or {}
    for entry in ("cad-deliver", "cad-deliver-mcp"):
        assert entry in scripts, f"missing console script {entry}"


def test_readme_files_exist():
    project = load()["project"]
    assert (ROOT / project["readme"]).is_file()
    # The Chinese README is linked from the English one; a dead link is a bad
    # first impression on GitHub and the file is small, so require it.
    assert (ROOT / "README.zh.md").is_file()


def test_classifiers_are_on_the_official_list():
    classifiers = load()["project"].get("classifiers") or []
    assert classifiers, "no classifiers declared"
    try:
        raw = urllib.request.urlopen(CLASSIFIER_URL, timeout=20).read().decode()
    except Exception as exc:  # noqa: BLE001 - offline is not a failure
        print(f"  skip (classifier list unreachable: {type(exc).__name__})")
        return
    valid = {line.strip() for line in raw.splitlines() if line.strip()}
    invalid = [c for c in classifiers if c not in valid]
    assert not invalid, (
        "PyPI will reject the upload with a 400 for these: "
        + "; ".join(invalid)
        + f" (checked against {len(valid)} official classifiers)"
    )


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\npackaging: {len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())