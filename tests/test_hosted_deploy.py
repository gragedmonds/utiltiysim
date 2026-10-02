"""The hosted engine (api/index.py, a Vercel Python function) has to be deployable as the repository is checked in:
every module it imports from this repository must reach Vercel (not left out by .vercelignore, not excluded from the
function bundle by vercel.json), and every helper module beside it in api/ must start with an underscore, or Vercel
deploys it as a function of its own. A missing module fails only at the function's cold start, which no local run
shows: this test imports the engine in a fresh process and checks what it loaded."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _vercelignore() -> list[str]:
    out = []
    for line in (ROOT / ".vercelignore").read_text().splitlines():
        p = line.strip()
        if p and not p.startswith("#"):
            out.append(p.strip("/"))
    return out


def _function_excludes() -> list[str]:
    pattern = json.loads((ROOT / "vercel.json").read_text())["functions"]["api/index.py"].get("excludeFiles", "")
    m = re.fullmatch(r"\{([^}]*)\}/\*\*", pattern)
    assert m, f"unexpected excludeFiles pattern {pattern!r}: update this test's parser"
    return m.group(1).split(",")


def _under(rel: str, prefixes: list[str]) -> str | None:
    return next((p for p in prefixes if rel == p or rel.startswith(p + "/")), None)


def _hosted_engine_modules() -> list[str]:
    """Repository files the hosted engine imports at cold start, relative to the repository root."""
    code = ("import json, sys\nimport api.index\n"
            "print(json.dumps(sorted(m.__file__ for m in list(sys.modules.values()) if getattr(m, '__file__', None))))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                         env={"PATH": "", "VERCEL": "1", "PYTHONPATH": str(ROOT)})
    assert out.returncode == 0, out.stderr[-2000:]
    files = [Path(f) for f in json.loads(out.stdout)]
    return sorted(str(f.relative_to(ROOT)) for f in files if f.is_relative_to(ROOT) and ".venv" not in f.parts)


def test_everything_the_hosted_engine_imports_reaches_vercel():
    ignored, excluded = _vercelignore(), _function_excludes()
    modules = _hosted_engine_modules()
    assert "api/index.py" in modules and any(m.startswith("utilsim/") for m in modules)
    missing = {m: f".vercelignore ({_under(m, ignored)})" for m in modules if _under(m, ignored)}
    missing.update({m: f"vercel.json excludeFiles ({_under(m, excluded)}/**)" for m in modules if _under(m, excluded)})
    assert not missing, f"api/index.py imports modules that never reach Vercel: {missing}"


def test_helper_modules_beside_the_function_are_private():
    ignored = _vercelignore()
    deployed = [p for p in sorted((ROOT / "api").glob("*.py")) if not _under(f"api/{p.name}", ignored)]
    public = [p.name for p in deployed if p.name != "index.py" and not p.name.startswith("_")]
    assert not public, f"Vercel would deploy these as functions of their own: {public} (rename with a leading underscore)"
