"""模板快速模式: 程序化按母版坐标渲染全部页面, 模型只做一次批量 KPI 小调用。

架构: 版式/文本布局全部由 Python 渲染 (单页 0 次模型调用);
唯一的模型环节是 batch_kpi — 8 条新闻的 KPI 选择+补充条合并成一次 JSON
调用 (输出 <1k 字符)。全 deck 分钟级完成。
"""
from __future__ import annotations
import json
import re
import threading
import time
from pathlib import Path

from . import checks
from .md_parser import parse_md
from .planner import plan_pages
from .prompts import page_user
from .render import gen_page
from .theme import get_theme

T = get_theme()
C = T["colors"]
DECOR = T["decor"]
COVER_DECOR = T["cover_decor"]
FONT = T["font"]
FS = 20          # 正文字号
LH = 27          # 行高


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_cover(doc_title: str, period: str, idx: int, total: int) -> str:
    fs = 44
    while _w(doc_title, fs) > 1100 and fs > 28:
        fs -= 2
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="1280" height="720" viewBox="0 0 1280 720" xmlns="http://www.w3.org/2000/svg">
{COVER_DECOR}
<g font-family="{FONT}">
<text x="640" y="340" font-size="{fs}" font-weight="bold" fill="{C['primary']}" text-anchor="middle">{_esc(doc_title)}</text>
<rect x="560" y="372" width="160" height="3" fill="{C['accent']}"/>
<text x="640" y="416" font-size="24" fill="{C['dark']}" text-anchor="middle">{_esc(period)}</text>
<text x="1167" y="682" font-size="16" fill="{C['dark']}" text-anchor="end">{idx} / {total}</text>
</g></svg>'''


def _w(s: str, fs: int) -> float:
    """估宽: CJK 全宽, ASCII 约 0.55 宽。"""
    return sum(fs if ord(c) > 0x2E80 else fs * 0.55 for c in s)


_NUMCHUNK = re.compile(r"\d[\d.,]*%?")


def _wrap(text: str, max_w: float, fs: int = FS) -> list[str]:
    """折行; 数字串(含小数点/千分位/%)为原子单位, 严禁从中间断开。"""
    lines, cur, cw = [], "", 0.0
    i = 0
    while i < len(text):
        m = _NUMCHUNK.match(text, i)
        tok = m.group(0) if m else text[i]
        i += len(tok)
        tw = _w(tok, fs)
        if cw + tw > max_w and cur:
            lines.append(cur)
            cur, cw = "", 0.0
            if tok == " ":
                continue
        cur += tok
        cw += tw
    if cur:
        lines.append(cur)
    return lines


def render_news(module: str, title: str, date: str, paras: list[str],
                kpis: list[dict], supplement: str, idx: int, total: int) -> str:
    # ── 标题 (超宽自动缩字号) ──
    full_title = f"{module}：{title}"
    fs = 34
    while _w(full_title, fs) > 1110 and fs > 24:
        fs -= 2
    # ── 段落折行 ──
    kpis = kpis[:2] if len(paras[0]) > 120 else kpis[:3]
    n = len(kpis)
    para1_x = 110 if n == 0 else 110 + n * 200 + 20
    l1 = _wrap(paras[0], 1190 - para1_x)
    rest = " ".join(paras[1:]) if len(paras) > 1 else ""
    l2 = _wrap(rest, 1080) if rest else []
    h1 = max(176 if n else 120, len(l1) * LH + 60, 176)
    # 溢出保护: 下溢时 KPI 改为顶部整行, 段落全宽重排
    card2_y = 200 + h1 + 14
    h2 = max(90, len(l2) * LH + 56)
    if card2_y + h2 + 54 > 655:
        kpis, n = kpis[:3], min(len(kpis), 3)
        para1_x = 110
        l1 = _wrap(paras[0], 1080)
        h1 = n * 96 + len(l1) * LH + 56 + 30
        l2 = _wrap(paras[1], 1080) if len(paras) > 1 else []
        card2_y = 200 + h1 + 14
        h2 = max(90, len(l2) * LH + 56)
    supp_y = min(card2_y + h2 + 20, 640)

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg width="1280" height="720" viewBox="0 0 1280 720" xmlns="http://www.w3.org/2000/svg">',
           DECOR,
           f'<g font-family="{FONT}">',
           '<g id="header">',
           f'<text x="77" y="123" font-size="{fs}" font-weight="bold" fill="{C["primary"]}">{_esc(full_title)}</text>',
           f'<text x="80" y="170" font-size="20" fill="{C["accent"]}">{date[:4]}年{int(date[5:7])}月{int(date[8:])}日 ｜ {_esc(module)}</text>',
           f'<rect x="80" y="184" width="1120" height="2" fill="{C["accent"]}"/>', '</g>',
           f'<g id="card1">',
           f'<rect x="80" y="200" width="1120" height="{h1}" rx="8" fill="#FFFFFF" stroke="{C["card_border"]}"/>',
           f'<rect x="80" y="200" width="6" height="{h1}" fill="{C["primary"]}"/>']
    if n == 0:                       # 段落独占
        y0 = 200 + (h1 - len(l1) * LH) // 2 + LH - 7
        out += [f'<text x="110" y="{y0 + i * LH}" font-size="{FS}" fill="{C["body"]}">{_esc(ln)}</text>'
                for i, ln in enumerate(l1)]
    elif para1_x == 110:             # 溢出保护布局: KPI 整行在上, 段落下
        for k, kp in enumerate(kpis):
            kx = 110 + k * 380
            out += [f'<rect x="{kx}" y="222" width="340" height="76" rx="8" fill="{C["card_bg"]}" stroke="{C["card_border"]}"/>',
                    f'<text x="{kx + 170}" y="264" font-size="40" font-weight="bold" fill="{C["primary"]}" text-anchor="middle">{_esc(kp["v"])}</text>',
                    f'<text x="{kx + 170}" y="288" font-size="20" fill="{C["dark"]}" text-anchor="middle">{_esc(kp["label"])}</text>']
        y0 = 330
        out += [f'<text x="110" y="{y0 + i * LH}" font-size="{FS}" fill="{C["body"]}">{_esc(ln)}</text>'
                for i, ln in enumerate(l1)]
    else:                            # 标准布局: KPI 左, 段落右 (母版样式)
        for k, kp in enumerate(kpis):
            kx = 110 + k * 200
            out += [f'<rect x="{kx}" y="247" width="180" height="76" rx="8" fill="{C["card_bg"]}" stroke="{C["card_border"]}"/>',
                    f'<text x="{kx + 90}" y="289" font-size="40" font-weight="bold" fill="{C["primary"]}" text-anchor="middle">{_esc(kp["v"])}</text>',
                    f'<text x="{kx + 90}" y="313" font-size="20" fill="{C["dark"]}" text-anchor="middle">{_esc(kp["label"])}</text>']
        y0 = 200 + (h1 - len(l1) * LH) // 2 + LH - 7
        out += [f'<text x="{para1_x}" y="{y0 + i * LH}" font-size="{FS}" fill="{C["body"]}">{_esc(ln)}</text>'
                for i, ln in enumerate(l1)]
    out += ['</g>', f'<g id="card2">',
            f'<rect x="80" y="{card2_y}" width="1120" height="{h2}" rx="8" fill="{C["card_bg"]}" stroke="{C["card_border"]}"/>',
            f'<rect x="80" y="{card2_y}" width="6" height="{h2}" fill="{C["primary"]}"/>']
    y20 = card2_y + (h2 - len(l2) * LH) // 2 + LH - 7
    out += [f'<text x="110" y="{y20 + i * LH}" font-size="{FS}" fill="{C["body"]}">{_esc(ln)}</text>'
            for i, ln in enumerate(l2)]
    out += ['</g>']
    if supplement:
        supp = supplement if len(supplement) <= 49 else supplement[:48] + "…"
        # 截断不得切开数字/百分比 (7.25亿 → 7.2… 事故): 剥掉尾部残缺数字串
        supp = re.sub(r"[\d.,]*\d[\d.,]*%?\…*$", "", supp)
        if len(supp) < 12:
            supp = supplement[:40]
        out += [f'<rect x="110" y="{supp_y}" width="1060" height="36" rx="6" fill="{C["bar_bg"]}"/>',
                f'<text x="130" y="{supp_y + 25}" font-size="20" fill="{C["primary"]}">补充：{_esc(supp)}</text>']
    out += [f'<text x="1167" y="682" font-size="16" fill="{C["dark"]}" text-anchor="end">{idx} / {total}</text>',
            '</g></svg>']
    return "\n".join(out)


def render_end(idx: int, total: int) -> str:
    e = T["end"]
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="1280" height="720" viewBox="0 0 1280 720" xmlns="http://www.w3.org/2000/svg">
{DECOR}
<g font-family="{FONT}">
<text x="640" y="380" font-size="72" font-weight="bold" fill="{C['primary']}" text-anchor="middle">{e['main']}</text>
<text x="640" y="440" font-size="20" fill="{C['dark']}" text-anchor="middle" letter-spacing="4">{e['sub']}</text>
<text x="1167" y="682" font-size="16" fill="{C['dark']}" text-anchor="end">{idx} / {total}</text>
</g></svg>'''


# ── 批量 KPI 小调用 (唯一模型环节) ─────────────────────────
KPI_SYS = """你是周报 PPT 的 KPI 编辑。为每条新闻从原文挑 0-2 个最关键的数字做 KPI 磁贴, 并选一句 ≤46 字的关键事实作补充条。
严格 JSON 输出: {"items":[{"i":1,"kpis":[{"v":"60天","label":"达成最终协议时限"}],"supplement":"…"}]}
硬规则: v 必须是原文逐字出现的数字串(含单位); label ≤10 字; 没有合适数字就给空数组; supplement 必须是原文连续子串(不含"补充："前缀), 无合适就空串。只输出 JSON。"""


def batch_kpi(llm, news_pages: list[dict]) -> list[dict]:
    lines = []
    for i, pg in enumerate(news_pages, 1):
        body = " ".join(pg["paras"])
        lines.append(f"# 新闻{i} ({pg['module']} | {pg['title']})\n{body}")
    usr = "共" + str(len(news_pages)) + "条:\n\n" + "\n\n".join(lines) + "\n\n请输出JSON:"
    try:
        raw = llm._chat(KPI_SYS, usr, disable_thinking=True, temperature=0.2,
                        json_mode=True, timeout=240)
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        got = {it.get("i"): it for it in data.get("items", [])}
    except Exception as e:
        print(f"[kpi] 批量调用失败, 全部走无KPI兜底: {str(e)[:120]}")
        got = {}
    out = []
    for i, pg in enumerate(news_pages, 1):
        it = got.get(i, {})
        body = "".join(pg["paras"])
        kpis = [k for k in it.get("kpis", [])[:2]
                if isinstance(k, dict) and k.get("v") and k["v"] in body][:2]
        supp = it.get("supplement", "") or ""
        if supp and supp not in body:
            supp = ""
        if not supp and pg["paras"]:   # 兜底: 末段第一句
            m = re.split(r"[。；]", pg["paras"][-1])
            supp = next((s + "。" for s in m if len(s) >= 10), "")
        out.append({"kpis": kpis, "supplement": supp[:49]})
    return out


def run_template(work: Path, out: Path | None, model: str | None,
                 llm_factory, on_event=None) -> list[bool]:
    """模板模式主流程: 渲染全部页 → 全页检查 → (可选)导出 pptx。

    on_event(phase, msg, **kw): 进度回调 (Web 任务态/CLI 打印共用);
        kw 可含 pages_total / pages_done。
    Returns: 每页检查结果列表 (True=通过)。
    """
    def _ev(phase: str, msg: str, **kw):
        if on_event is not None:
            on_event(phase, msg, **kw)

    svg_dir = work / "svg"
    svg_dir.mkdir(exist_ok=True)

    doc = parse_md((work / "input.md").read_text(encoding="utf-8"))
    pages = plan_pages(doc)
    total = len(pages)
    _ev("plan", f"页面计划 {total} 页: {[p['type'] for p in pages]}",
        pages_total=total)
    print(f"模板模式: {total} 页, 模型环节仅 1 次批量 KPI 调用")
    news_pages = [p for p in pages if p["type"] == "news"]

    t0 = time.time()
    kpi_cache = work / "kpi_cache.json"
    llm = None
    if kpi_cache.exists():
        kpis = json.loads(kpi_cache.read_text(encoding="utf-8"))
        _ev("kpi", "KPI 抽取: 使用缓存")
        print(f"[kpi] 使用缓存 {kpi_cache}")
    else:
        llm = llm_factory(model)
        _ev("kpi", "KPI 批量抽取中 (唯一模型环节, 约 30-60s)…")
        kpis = batch_kpi(llm, news_pages)
        kpi_cache.write_text(json.dumps(kpis, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        _ev("kpi", f"KPI 批量调用完成 ({time.time()-t0:.0f}s)")
        print(f"[kpi] 批量调用 {time.time()-t0:.0f}s: "
              f"{[(k['kpis'] and len(k['kpis'])) or 0 for k in kpis]}")

    k = 0
    m = re.search(r"[（(](\d{2})/(\d{2})-(\d{2})/(\d{2})[)）]", doc["doc_title"])
    year = news_pages[0]["date"][:4] if news_pages else "2026"
    period = (f"{year}年{int(m.group(1))}月{int(m.group(2))}日至"
              f"{int(m.group(3))}月{int(m.group(4))}日") if m else ""
    # 无母版页型 (数据页等) → 后台线程模型生成; 不阻塞其余页的渲染与检查
    model_pages: list[tuple[int, dict]] = []
    for i, pg in enumerate(pages, 1):
        dst = svg_dir / f"page_{i:02d}.svg"
        if pg["type"] == "cover":
            dst.write_text(render_cover(doc["doc_title"], period, i, total),
                           encoding="utf-8")
        elif pg["type"] == "news":
            k += 1
            dst.write_text(render_news(pg["module"], pg["title"], pg["date"],
                                       pg["paras"], kpis[k-1]["kpis"],
                                       kpis[k-1]["supplement"], i, total),
                           encoding="utf-8")
        elif pg["type"] == "end":
            dst.write_text(render_end(i, total), encoding="utf-8")
        elif not dst.exists():
            model_pages.append((i, pg))

    gen_thread = None
    gen_results: dict[int, tuple[str, list[str]]] = {}
    if model_pages:
        if llm is None:
            llm = llm_factory(model)

        def _gen_model_pages():
            for i, pg in model_pages:
                _ev("gen", f"P{i:02d}({pg['type']}) 无母版, 模型后台生成中 "
                           f"(约 5-15 分钟, 不阻塞其他页检查)…")
                print(f"[reuse-miss] P{i:02d}({pg['type']}) 无母版, 走模型生成…", flush=True)
                gen_results[i] = gen_page(llm, pg, i, total, doc, work,
                                          on_event=lambda m: _ev("gen", m))
                svg, iss = gen_results[i]
                if svg:
                    (svg_dir / f"page_{i:02d}.svg").write_text(svg, encoding="utf-8")
                else:
                    print(f"  [P{i:02d}] ✗ 模型生成失败: {'; '.join(iss)[:200]}")

        gen_thread = threading.Thread(target=_gen_model_pages, daemon=True)
        gen_thread.start()
    # 页码修正: 复用旧母版页若为旧总页数口径
    for f in svg_dir.glob("page_*.svg"):
        t = f.read_text(encoding="utf-8")
        t2 = re.sub(r"(\d+) / \d+<", rf"\1 / {total}<", t)
        if t2 != t:
            f.write_text(t2, encoding="utf-8")
    # 全页检查 + 渲染 (srcs/extra 与 prompts.page_user 同源, 口径一致)
    # 模型页在后台生成期间, 先检查其余页 → 进度条先走起来
    model_idx = {i for i, _ in model_pages}
    check_order = [i for i in range(1, total + 1) if i not in model_idx]
    if gen_thread is not None:
        check_order += sorted(model_idx)   # 模型页最后查 (此时后台线程已完成)
    ok_list = []
    done_count = 0
    for i in check_order:
        pg = pages[i - 1]
        # 模型页: 先等后台线程收尾, 再判文件存在性 (顺序反了会把
        # 生成中的页误判"缺页" — 2026-10-11 事故, 本次修复)
        if i in model_idx and gen_thread is not None:
            _ev("gen", "其余页检查完毕, 等待模型页收尾…")
            gen_thread.join()
            gen_thread = None
        f = svg_dir / f"page_{i:02d}.svg"
        done_count += 1
        if not f.exists():
            print(f"  [P{i:02d}] 缺页!")
            _ev("page", f"P{i:02d} 缺页 ✗", pages_done=done_count)
            ok_list.append(False)
            continue
        svg = f.read_text(encoding="utf-8")
        _, srcs, extra = page_user(pg, i, total, doc)
        if pg["type"] == "cover":
            ok, issues, _ = checks.run_all(svg, work, srcs, extra,
                                           png_dir=work / "png", page_tag=f"p{i:02d}",
                                           min_ratio=0.003,
                                           min_imgs=T["cover_min_imgs"])
        else:
            ok, issues, _ = checks.run_all(svg, work, srcs, extra,
                                           png_dir=work / "png", page_tag=f"p{i:02d}",
                                           min_ratio=0.003 if pg["type"] == "end" else 0.02)
        ok_list.append(ok)
        line = f"[P{i:02d}] {'✓' if ok else '✗ ' + '; '.join(issues)[:120]}"
        print("  " + line)
        _ev("page", line, pages_done=done_count)
    print(f"检查通过 {sum(ok_list)}/{total}")
    _ev("check", f"检查通过 {sum(ok_list)}/{total}")

    if out is not None:
        from .exporter import export_pptx
        _ev("export", "导出 PPTX 中…")
        export_pptx(work, out)
    return ok_list
