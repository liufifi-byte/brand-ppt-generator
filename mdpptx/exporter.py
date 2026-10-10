"""PPTX 导出: work/svg/*.svg → 单个 .pptx (vendored svg_to_pptx 转换器)。"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONVERTER = REPO_ROOT / "converter" / "run_converter.py"


def export_pptx(work: Path, out: Path) -> bool:
    """把 work/svg 下的页面 SVG 合并导出为 pptx。返回是否成功。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(CONVERTER), str(work),
         "-s", "svg", "-o", str(out), "-f", "ppt169", "-q"],
        capture_output=True, text=True)
    ok = r.returncode == 0 and out.exists()
    print("导出:", "✓ " + str(out) if ok else "✗ " + (r.stderr[-300:] or r.stdout[-300:]))
    return ok
