"""统一 CLI。

用法:
    python -m mdpptx init                     # 初始化 work/ (从 sample 拷贝示例)
    python -m mdpptx generate --pages 3       # SVG 生成模式 (试点前 3 页)
    python -m mdpptx generate --full --out 周报.pptx
    python -m mdpptx template --out 周报.pptx # 模板快速模式 (分钟级全 deck)
"""
from __future__ import annotations
import argparse
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .llm import LLMClient
from .md_parser import parse_md
from .planner import plan_pages
from .render import gen_page

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "sample"
WORK_DEFAULT = REPO_ROOT / "work"


def _llm_factory(model: str | None) -> LLMClient:
    return LLMClient(model)


def cmd_init(args) -> None:
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    (work / "svg").mkdir(exist_ok=True)
    if args.empty:
        print(f"work 目录就绪 (空): {work}\n把你的周报 md 放到 work/input.md, "
              f"品牌图片放到 work/assets/ (image1.png~image6, 见 README)")
        return
    shutil.copy(SAMPLE / "input.md", work / "input.md")
    shutil.copytree(SAMPLE / "assets", work / "assets", dirs_exist_ok=True)
    print(f"work 目录就绪 (已拷贝示例): {work}\n"
          f"替换 work/input.md 为你的周报, 换品牌图改 work/assets/ 与 mdpptx/theme.py")


def cmd_generate(args) -> None:
    work = Path(args.work)
    md = (work / "input.md").read_text(encoding="utf-8")
    doc = parse_md(md)
    pages = plan_pages(doc)
    total = len(pages)
    if args.pages:
        pages, total = pages[:args.pages], args.pages
    print(f"页面计划 {len(pages)} 页: {[p['type'] for p in pages]}")
    print(f"文档: {doc['doc_title']} | 模块: {[m['name'] for m in doc['modules']]}")

    llm = _llm_factory(args.model)
    print(f"模型: {llm.model}")
    (work / "svg").mkdir(exist_ok=True)

    failures = []
    t0 = time.time()
    # 页间并行: 版式由规范锁死, 页间无依赖; 失败页不阻塞其他页
    def _task(i_pg):
        i, pg = i_pg
        svg, issues = gen_page(llm, pg, i, total, doc, work)
        if svg:
            (work / "svg" / f"page_{i:02d}.svg").write_text(svg, encoding="utf-8")
        return i, bool(svg), not issues
    done_log = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(_task, x): x[0] for x in enumerate(pages, 1)}
        for fut in as_completed(futs):
            i, has_svg, clean = fut.result()
            done_log.append(i)
            print(f"  [done] P{i:02d} ({len(done_log)}/{len(pages)}) "
                  f"累计 {time.time()-t0:.0f}s", flush=True)
    print(f"生成完毕 {time.time()-t0:.0f}s, 完成 {len(done_log)}/{len(pages)} 页")

    if args.out or args.full:
        out = Path(args.out) if args.out else REPO_ROOT / f"{doc['doc_title'][:20]}_SVG模式.pptx"
        from .exporter import export_pptx
        export_pptx(work, out)


def cmd_template(args) -> None:
    from .template_mode import run_template
    work = Path(args.work)
    out = Path(args.out) if args.out else None
    run_template(work, out, args.model, _llm_factory)


def main() -> None:
    ap = argparse.ArgumentParser(prog="mdpptx",
                                 description="Markdown 周报 → 品牌 PPT 生成器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化 work 目录")
    p_init.add_argument("--work", default=str(WORK_DEFAULT))
    p_init.add_argument("--empty", action="store_true", help="不拷贝示例, 建空目录")
    p_init.set_defaults(func=cmd_init)

    p_gen = sub.add_parser("generate", help="SVG 生成模式 (逐页 LLM + 校验修复环)")
    p_gen.add_argument("--work", default=str(WORK_DEFAULT))
    p_gen.add_argument("--pages", type=int, default=0, help="只生成前 N 页 (试点)")
    p_gen.add_argument("--full", action="store_true")
    p_gen.add_argument("--model", default=None)
    p_gen.add_argument("--concurrency", type=int, default=3, help="页间并行度")
    p_gen.add_argument("--out", default=None, help="导出 pptx 路径")
    p_gen.set_defaults(func=cmd_generate)

    p_tpl = sub.add_parser("template", help="模板快速模式 (程序化渲染 + 1 次批量 KPI 调用)")
    p_tpl.add_argument("--work", default=str(WORK_DEFAULT))
    p_tpl.add_argument("--model", default=None)
    p_tpl.add_argument("--out", default=None, help="导出 pptx 路径")
    p_tpl.set_defaults(func=cmd_template)

    args = ap.parse_args()
    args.func(args)
