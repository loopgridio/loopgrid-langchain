"""Static source/release documentation audit: deterministic, Python 3.10+ compatible."""
from __future__ import annotations
from pathlib import Path
import re
try:
    import tomllib as _tomllib
except ImportError:
    import tomli as _tomllib

root = Path(__file__).resolve().parents[1]
with (root / "pyproject.toml").open("rb") as fh:
    project = _tomllib.load(fh)["project"]
assert project["name"] == "loopgrid-langchain"
assert project["version"] == "0.1.0"
required = ("README.md", "CHANGELOG.md", "VALIDATION.md", "SECURITY.md",
            "INTEGRATION-CONTRACT.md", "LICENSE", "NOTICE.md",
            "docs/RELEASE-ENGINEERING.md", "docs/LOCAL-VALIDATION.md")
for name in required:
    assert (root / name).is_file(), "Missing source file: " + name
for name in (".venv/", ".consumer-venv/", "dist/", "build/", ".coverage", ".env"):
    assert name in (root / ".gitignore").read_text(encoding="utf-8"), "Unignored build/secret artifact: " + name
for name in ("README.md", "CHANGELOG.md"):
    text = (root / name).read_text(encoding="utf-8")
    assert not re.search(r"\b(?:unpublished|release candidate|not released|pending windows|not yet validated|rc[12])\b", text, re.I), "Stale release text: " + name
for md in root.rglob("*.md"):
    if any(part.startswith(".") for part in md.relative_to(root).parts):
        continue
    value = md.read_text(encoding="utf-8")
    for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", value):
        target = target.split("#", 1)[0].split("?", 1)[0].strip()
        if not target or re.match(r"^(https?://|mailto:)", target, re.I):
            continue
        assert (md.parent / target).exists(), f"Broken local Markdown link in {md}: {target}"
assert (root / ".github/workflows/tests.yml").is_file()
assert (root / ".github/workflows/release.yml").is_file()
print("PASS: release documentation, local links, package identity, exclusions, CI workflows")
