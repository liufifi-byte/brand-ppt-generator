"""统一 CLI。

用法:
    python -m mdpptx serve --port 8020        # 起 Web 服务 (上传文档 → 生成 PPT)
    python -m mdpptx init                     # 初始化 work/ (从 sample 拷贝示例)
    python -m mdpptx generate --pages 3       # SVG 生成模式 (试点前 3 页)
    python -m mdpptx generate --full --out 周报.pptx
    python -m mdpptx template --out 周报.pptx # 模板快速模式 (分钟级全 deck)
"""
from __future__ import annotations
import argparse
import shutil
from pathlib import Path

from .llm import LLMClient

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
    from .runner import run_generate
    work = Path(args.work)
    out = (Path(args.out) if args.out else None) if (args.out or args.full) else None
    if args.full and not args.out:
        from .md_parser import parse_md
        title = parse_md((work / "input.md").read_text(encoding="utf-8"))["doc_title"]
        out = REPO_ROOT / f"{title[:20]}_SVG模式.pptx"
    run_generate(work, out, args.model, args.concurrency, _llm_factory,
                 pages_limit=args.pages)


def cmd_template(args) -> None:
    from .template_mode import run_template
    work = Path(args.work)
    out = Path(args.out) if args.out else None
    run_template(work, out, args.model, _llm_factory)


def cmd_serve(args) -> None:
    import uvicorn
    from .server import app
    print(f"Web 服务: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def main() -> None:
    ap = argparse.ArgumentParser(prog="mdpptx",
                                 description="Markdown 周报 → 品牌 PPT 生成器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="起 Web 服务 (上传文档 → 生成 PPT)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8020)
    p_serve.set_defaults(func=cmd_serve)

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
