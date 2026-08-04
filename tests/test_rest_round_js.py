"""F131 ①④：`adoptNativeRound()` 的接手邏輯——用 node 直接跑 state.js。

為什麼值得測：這條路的 bug 不會當場報錯，只會讓畫面比通知列多算幾十秒
（背景時 restControl 事件會遲到，從「現在」重數就分叉）。純函式、可測，就測。
需要 node（前端本來就用它做語法檢查）；沒有 node 的環境自動跳過。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATE_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "state.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="需要 node")


def run_case(script: str) -> dict:
    source = f"""
    import {{ state, adoptNativeRound, restElapsedSeconds }} from "file:///{
        STATE_JS.as_posix()
    }";
    {script}
    console.log(JSON.stringify({{
      startedAt: state.restStartedAt,
      resumedAt: state.restResumedAt,
      accumulatedMs: state.restAccumulatedMs,
      target: state.restTargetSeconds,
      pendingRestSeconds: state.pendingRestSeconds,
      elapsed: restElapsedSeconds(),
    }}));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "--eval", source],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_adopt_uses_native_start_time_not_now():
    """事件遲到 30 秒才處理時，仍以原生那一輪的開始時刻為準。"""
    out = run_case("adoptNativeRound(120, Date.now() - 30000);")
    assert out["target"] == 120
    # 已休息 30 秒（容忍 1 秒的執行誤差）
    assert 29 <= out["elapsed"] <= 31
    assert out["accumulatedMs"] == 0


def test_adopt_falls_back_to_now_for_bogus_timestamp():
    """未來時間／0／NaN 都不可信——寧可從現在開始，也不要算出負的已休息秒數。"""
    for bogus in ("0", "Date.now() + 60000", "NaN"):
        out = run_case(f"adoptNativeRound(90, {bogus});")
        assert out["elapsed"] == 0, bogus
        assert out["target"] == 90


def test_adopt_clears_frozen_rest_seconds():
    """這一輪還沒結束，凍結值不得留著被下一組當成組間休息取用（F15／F129）。"""
    out = run_case("state.pendingRestSeconds = 77; adoptNativeRound(60, Date.now());")
    assert out["pendingRestSeconds"] is None
