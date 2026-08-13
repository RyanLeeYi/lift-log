"""F138 regression guard: every tests/e2e script must pin UTF-8 stdout itself.

Run it from a plain Windows console (cp950, no PYTHONUTF8 / PYTHONIOENCODING):

    uv run python tests/e2e/smoke_encoding.py

Each script is imported in its own subprocess; the child then prints the
characters that used to blow up (>=, (1), warning sign). A script that forgot to
call ``sys.stdout.reconfigure`` fails there with UnicodeEncodeError, which is the
exact failure F138 exists to prevent.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 這支自己也會印 ≥ 與子行程的中文錯誤訊息，同樣不能依賴呼叫端的環境變數（F138）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

E2E_DIR = Path(__file__).resolve().parent
CANARY = "≥①⚠"  # ≥ ① ⚠ — all unencodable in cp950

CHILD = """
import importlib, sys
sys.path.insert(0, {e2e!r})
m = importlib.import_module({module!r})
assert sys.stdout.encoding.lower().replace("-", "") == "utf8", sys.stdout.encoding
print({canary!r})
"""


def scripts() -> list[Path]:
    return sorted(
        p
        for p in E2E_DIR.glob("*.py")
        if p.name not in {"__init__.py", Path(__file__).name}
    )


def check(path: Path) -> tuple[bool, str]:
    code = CHILD.format(e2e=str(E2E_DIR), module=path.stem, canary=CANARY)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return False, tail[-1] if tail else f"exit {proc.returncode}"
    return True, ""


def main() -> int:
    failures = []
    targets = scripts()
    for path in targets:
        ok, detail = check(path)
        print(f"{'PASS' if ok else 'FAIL'}  {path.name}{'' if ok else '  ' + detail}")
        if not ok:
            failures.append(path.name)

    print(f"\n{len(targets) - len(failures)}/{len(targets)} scripts pin UTF-8 stdout")
    if failures:
        print("FAILED: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
