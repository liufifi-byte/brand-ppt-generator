"""生成模式编排 (CLI 与 Web 服务共用): 逐页 LLM 生成 + 检查修复环。"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .llm import LLMClient
from .md_parser import parse_md
from .planner import plan_pages
from .render import gen_page


def run_generate(work: Path, out: Path | None, model: str | None,
                 concurrency: int, llm_factory, on_event=None,
                 pages_limit: int = 0) -> list[bool]:
    """SVG 生成模式: 页间并行逐页生成 → 导出。

    on_event(phase, msg, **kw): 进度回调 (同 run_template)。
    pages_limit>0 时只生成前 N 页 (试点)。
    Returns: 每页是否有产物 (True=svg 已落盘)。
    """
    def _ev(phase: str, msg: str, **kw):
        if on_event is not None:
            on_event(phase, msg, **kw)

    md = (work / "input.md").read_text(encoding="utf-8")
    doc = parse_md(md)
    pages = plan_pages(doc)
    total = len(pages)
    if pages_limit:
        pages, total = pages[:pages_limit], pages_limit
    plan_line = f"页面计划 {len(pages)} 页: {[p['type'] for p in pages]}"
    print(plan_line)
    print(f"文档: {doc['doc_title']} | 模块: {[m['name'] for m in doc['modules']]}")
    _ev("plan", plan_line + f" · {doc['doc_title']}", pages_total=total)

    llm: LLMClient = llm_factory(model)
    _ev("gen", f"模型: {llm.model}, 页间并行 {concurrency} 路, 单页约 15s-5min")
    print(f"模型: {llm.model}")
    (work / "svg").mkdir(exist_ok=True)

    t0 = time.time()

    def _task(i_pg):
        i, pg = i_pg
        svg, issues = gen_page(llm, pg, i, total, doc, work)
        if svg:
            (work / "svg" / f"page_{i:02d}.svg").write_text(svg, encoding="utf-8")
        return i, bool(svg), not issues

    results = {}
    done_n = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(_task, x): x[0] for x in enumerate(pages, 1)}
        for fut in as_completed(futs):
            i, has_svg, clean = fut.result()
            done_n += 1
            results[i] = has_svg
            line = (f"P{i:02d} 完成 ({'检查通过' if clean else '有未修复问题'})"
                    f" · {done_n}/{len(pages)} · 累计 {time.time()-t0:.0f}s")
            print(f"  [done] {line}", flush=True)
            _ev("page", line, pages_done=done_n)
    print(f"生成完毕 {time.time()-t0:.0f}s, 完成 {len(results)}/{len(pages)} 页")
    _ev("check", f"生成完毕, 完成 {len(results)}/{len(pages)} 页 "
                 f"({time.time()-t0:.0f}s)")

    if out is not None:
        from .exporter import export_pptx
        _ev("export", "导出 PPTX 中…")
        export_pptx(work, out)
    return [bool(results.get(i)) for i in range(1, len(pages) + 1)]
