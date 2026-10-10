"""PPT 模板接入 (v1): 从上传的 .pptx 提取主题色, 覆盖生成色板。

读 ppt/theme/theme1.xml 的 clrScheme (accent1-6 / dk2):
  primary=accent1, secondary=accent2, accent=accent3,
  highlight=accent4, dark=dk2 (黑或接近黑则用默认深灰)
中性色 (正文/卡片底) 不动 — 保证可读性。装饰图沿用默认品牌图。
"""
from __future__ import annotations
import re
import zipfile
from pathlib import Path

# 颜色覆盖键 → clrScheme 中的槽位
_SLOT_MAP = {
    "primary": "accent1",
    "secondary": "accent2",
    "accent": "accent3",
    "highlight": "accent4",
    "dark": "dk2",
}


def extract_theme_override(pptx_path: Path) -> dict:
    """返回 {"name": ..., "colors": {...}} (仅含成功解析的键)。"""
    with zipfile.ZipFile(pptx_path) as z:
        theme_files = [n for n in z.namelist()
                       if re.match(r"ppt/theme/theme\d+\.xml", n)]
        if not theme_files:
            return {}
        xml = z.read(sorted(theme_files)[0]).decode("utf-8", errors="ignore")

    m = re.search(r"<a:clrScheme[^>]*>(.*?)</a:clrScheme>", xml, re.S)
    if not m:
        return {}
    scheme = m.group(1)
    colors: dict[str, str] = {}
    for key, slot in _SLOT_MAP.items():
        sm = re.search(
            rf'<a:{slot}>.*?(?:<a:srgbClr val="([0-9A-Fa-f]{{6}})"|'
            rf'<a:sysClr[^>]*lastClr="([0-9A-Fa-f]{{6}})")', scheme, re.S)
        if not sm:
            continue
        hexv = (sm.group(1) or sm.group(2)).upper()
        # 纯黑/纯白不作 dark (正文可读性)
        if key == "dark" and hexv in ("000000", "FFFFFF"):
            continue
        colors[key] = f"#{hexv}"
    out: dict = {"colors": colors}
    nm = re.search(r'<a:clrScheme[^>]*name="([^"]+)"', xml)
    if nm:
        out["name"] = f"模板 · {nm.group(1)}"
    return out if colors else {}
