"""SVG 页面检查器: XML / 清洁 / 装饰 / verbatim 数字 / 渲染像素。

harness 的"尺子" — 每项检查返回 (ok, 问题清单), 问题清单可直接拼进修复提示词。
渲染检查用 cairosvg; EMF 图 cairosvg 会崩 → 渲染副本中以同位矩形替换
(仅预览用, 导出 PPTX 时仍嵌原始 EMF)。
"""
from __future__ import annotations
import re
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

CLEAN_PATTERNS = [
    (r"source\s*:", "溯源标注 source:"),
    (r"docx\s*\[", "溯源标注 docx ["),
    (r"源自", "溯源标注 源自"),
    (r"\[source", "溯源标注 [source"),
    (r"注：", "来源说明行 注："),
    (r'fill="(PRIMARY|ACCENT|WARN|SUCCESS)"', "占位色未替换"),
    (r"foreignObject", "foreignObject (导出不支持)"),
    (r"<animate", "动画标签 (导出不支持)"),
]


def check_xml(svg: str) -> tuple[bool, list[str]]:
    try:
        ET.fromstring(svg)
        return True, []
    except ET.ParseError as e:
        return False, [f"XML 不合法: {e}"]


def check_clean(svg: str) -> tuple[bool, list[str]]:
    issues = [why for pat, why in CLEAN_PATTERNS if re.search(pat, svg)]
    return not issues, issues


def check_decoration(svg: str, min_imgs: int = 4) -> tuple[bool, list[str]]:
    n = len(re.findall(r"<image\s", svg))
    return n >= min_imgs, \
        [f"装饰图仅 {n} 张 (<{min_imgs}), 装饰层须完整回放"] if n < min_imgs else []


def _svg_text(svg: str) -> str:
    """抽取全部 <text>/<tspan> 文字, 按文档序以空格拼接 (数字提取用, 防跨节点粘连)。"""
    root = ET.fromstring(svg)
    parts = [t.text or "" for t in root.iter() if t.tag.endswith(("text", "tspan"))]
    return " ".join(parts)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).replace("\\.", ".").replace("\\,", ",")


def _nums(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", s))


def check_verbatim(svg: str, source_texts: list[str],
                   extra_allowed: set[str] | None = None) -> tuple[bool, list[str]]:
    """素材段落 verbatim 命中 + SVG 数字不得超出素材数字集。"""
    issues = []
    raw = _svg_text(svg)
    joined_n = _norm(raw)
    # 1) 每段素材 (≥12字) 必须逐字出现 (去空白比对; 允许跨 text 行拼接)
    for s in source_texts:
        s_n = _norm(s)
        if len(s_n) >= 12 and s_n not in joined_n:
            issues.append(f"以下素材未逐字出现(检查是否改写/漏字): {s[:50]}…")
    # 2) SVG 里的数字 ∈ 素材数字 ∪ 白名单 (在原始拼接上提取, 防跨节点粘连)
    allowed = set()
    for s in source_texts:
        allowed |= _nums(s)
    allowed |= (extra_allowed or set())
    svg_nums = _nums(raw)
    bad = sorted(n for n in svg_nums - allowed if len(n) >= 1)
    if bad:
        issues.append(f"SVG 出现素材外的数字: {bad[:12]}")
    return not issues, issues


def check_covering(svg: str) -> tuple[bool, list[str]]:
    """装饰层之后出现全页级大面积矩形 → 会盖住边框/logo, 判失败。"""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return True, []   # XML 检查会报
    past_deco = False
    issues = []
    for el in root.iter():
        if el.tag.endswith("}g") or el.tag.endswith("}svg"):
            if el.get("id") == "decoration":
                past_deco = True
            continue
        if past_deco and el.tag.endswith("}rect"):
            try:
                w, h = float(el.get("width", 0)), float(el.get("height", 0))
            except ValueError:
                continue
            if w >= 1150 and h >= 650:
                issues.append(
                    f"全页矩形 ({w:.0f}x{h:.0f}) 画在装饰层之后, 会遮挡边框/logo — "
                    f"删除它或改画在装饰层之前")
    return not issues, issues


def render_png(svg: str, work_dir: Path, out_png: Path) -> Path | None:
    """cairosvg 渲染 (EMF→同位矩形, href→绝对路径)。失败返回 None。"""
    try:
        import cairosvg
    except ImportError:
        return None
    tmp = svg
    # EMF 占位 (渲染专用, 不改写原 SVG): 从 image 标签读自身坐标画同位矩形
    def _emf_rect(m):
        tag = m.group(0)
        def attr(name, default):
            mm = re.search(rf'{name}="([\d.]+)"', tag)
            return mm.group(1) if mm else default
        return (f'<rect x="{attr("x", 0)}" y="{attr("y", 0)}" '
                f'width="{attr("width", 100)}" height="{attr("height", 10)}" '
                f'fill="#004A86"/>')
    tmp = re.sub(r'<image[^>]*href="[^"]*\.emf"[^>]*/?>', _emf_rect, tmp)
    # 相对 href → 绝对 (兼容 xlink:href; ../assets 相对于 work/svg/ 目录解析)
    svg_base = work_dir / "svg"

    def _abs(m):
        href = m.group(2)
        p = (svg_base / href).resolve()
        return f'{m.group(1)}href="{p.as_uri()}"' if p.exists() else m.group(0)
    tmp = re.sub(r'(xlink:|)href="(\.\./[^"]+)"', _abs, tmp)
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False,
                                     encoding="utf-8") as f:
        f.write(tmp)
        tmp_path = f.name
    try:
        cairosvg.svg2png(bytestring=None, url=tmp_path, write_to=str(out_png),
                         output_width=1280, output_height=720, unsafe=True)
        return out_png
    except Exception:
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def check_pixels(png: Path, min_ratio: float = 0.02) -> tuple[bool, list[str]]:
    """像素级: 非白占比 (防白页/内容过稀)。极简页型 (结尾页) 传更低的 min_ratio。"""
    try:
        from PIL import Image
    except ImportError:
        return True, []
    im = Image.open(png).convert("L")
    px = im.load()
    w, h = im.size
    total = nonwhite = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            total += 1
            if px[x, y] < 245:
                nonwhite += 1
    ratio = nonwhite / total if total else 0
    ok = min_ratio < ratio < 0.92
    issues = []
    if ratio <= min_ratio:
        issues.append(f"页面近乎空白 (非白像素 {ratio:.1%}) — 内容可能没画出来")
    if ratio >= 0.92:
        issues.append(f"页面过满 (非白像素 {ratio:.1%}) — 可能大面积色块遮蔽")
    return ok, issues


def run_all(svg: str, work_dir: Path, source_texts: list[str],
            extra_nums: set[str] | None = None, png_dir: Path | None = None,
            page_tag: str = "page", min_ratio: float = 0.02,
            min_imgs: int = 4) -> tuple[bool, list[str], Path | None]:
    """跑全部检查, 返回 (ok, 问题清单, 渲染PNG路径)。"""
    issues: list[str] = []
    ok, iss = check_xml(svg)
    issues += iss
    ok, iss = check_clean(svg)
    issues += iss
    ok, iss = check_decoration(svg, min_imgs)
    issues += iss
    ok, iss = check_covering(svg)
    issues += iss
    ok, iss = check_verbatim(svg, source_texts, extra_nums)
    issues += iss
    png = None
    if png_dir is not None and not issues:  # 结构过了才渲染 (省时间)
        png_dir.mkdir(exist_ok=True)
        png = render_png(svg, work_dir, png_dir / f"{page_tag}.png")
        if png is None:
            issues.append("SVG 渲染失败 (cairosvg) — 检查语法/引用")
        else:
            ok, iss = check_pixels(png, min_ratio)
            issues += iss
    return not issues, issues, png
