"""渲染层: 模型输出后处理 (装饰注入/清理) + 逐页生成-检查-修复环。

gen_page 是 SVG 模式的核心循环:
    user prompt → LLM 生成 → post_fix → checks.run_all
    → 未过: 问题清单拼进提示词重写 (≤max_rounds 轮)
"""
from __future__ import annotations
import os
import re
import time
from pathlib import Path

from . import checks
from .prompts import build_sys, page_user
from .theme import get_theme

T = get_theme()

# 单次调用超时 (秒): "始终思考"档模型在大 prompt (SYS+素材) 上单页生成
# 常在 200-300s 量级, 240s 边界会间歇性读超时 → 默认 360s, 可环境变量覆盖
CALL_TIMEOUT = int(os.environ.get("MDPPT_CALL_TIMEOUT", "360"))


def post_fix(svg: str) -> str:
    """模型输出后处理: 剥围栏 → 注入装饰层 → 补 XML 声明 → 清危险标签/规整 href。"""
    svg = svg.strip()
    if svg.startswith("```"):
        svg = svg.split("\n", 1)[1] if "\n" in svg else svg
    if svg.endswith("```"):
        svg = svg.rsplit("```", 1)[0]
    svg = svg.strip()
    # 装饰图层注入: 模型只画内容层, 品牌装饰图统一叠加 (省输出+保一致)
    if "<image" not in svg and 'id="decoration"' not in svg:
        m = re.search(r"(<svg[^>]*>)", svg)
        if m:
            svg = svg[:m.end()] + "\n" + T["decor"] + svg[m.end():]
    if not svg.startswith("<?xml"):
        svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg
    # 防御: 剥掉模型画的全页背景矩形 (会盖住装饰层的边框/logo)
    svg = re.sub(r'<rect[^>]*width="1[12][0-9]{2}"[^>]*height="[67][0-9]{2}"[^>]*/?\s*>', "", svg)
    svg = re.sub(r"<animate[^>]*?/>", "", svg)
    svg = re.sub(r"<animate[^>]*?>.*?</animate>", "", svg, flags=re.S)
    svg = re.sub(r'href="(?!\.{0,2}/|data:|http)', 'href="../assets/', svg)
    svg = re.sub(r"(\.\./assets/)image_0*(\d+)\.", r"\1image\2.", svg)
    return svg


def gen_page(llm, pg: dict, idx: int, total: int, doc: dict,
             work: Path, max_rounds: int = 3, on_event=None) -> tuple[str, list[str]]:
    """生成一页: 检查未过则带问题清单重写, 最多 max_rounds 轮。

    on_event(msg): 单字符串心跳 (Web 任务日志用); 每轮调用前后各发一条,
    单次调用最长 CALL_TIMEOUT 秒, 期间静默属正常。
    Returns:
        (svg, 问题清单) — 问题清单为空 = 通过; 用尽轮次返回最后一稿+问题。
    """
    def ev(msg: str):
        if on_event is not None:
            on_event(msg)

    usr, srcs, extra = page_user(pg, idx, total, doc)
    history = ""
    last_svg = ""
    issues: list[str] = []
    t0 = time.time()
    for rnd in range(1, max_rounds + 1):
        prompt = usr if not history else (
            usr + f"\n\n# 上一稿问题 (第{rnd-1}轮, 必须全部修复; "
                  f"逐条对照检查后重输完整 SVG):\n{history}\n\n上一稿 SVG:\n" + last_svg)
        tc0 = time.time()
        ev(f"P{idx:02d} 第{rnd}轮 生成中（单轮最长约 {CALL_TIMEOUT//60} 分钟, 请稍候）…")
        try:
            raw = llm._chat(build_sys(), prompt,
                            disable_thinking=True, temperature=0.2,
                            timeout=CALL_TIMEOUT)
        except Exception as e:
            msg = f"LLM 调用失败 (超时预算{CALL_TIMEOUT}s): {str(e)[:160]}"
            print(f"  [P{idx:02d}] ✗ {msg}", flush=True)
            ev(f"P{idx:02d} ✗ {msg[:120]}")
            return last_svg, [msg]
        print(f"    [call] {time.time()-tc0:.0f}s out={len(raw)}ch", flush=True)
        svg = post_fix(raw)
        last_svg = svg
        ok, issues, _ = checks.run_all(svg, work, srcs, extra,
                                       png_dir=work / "png", page_tag=f"p{idx:02d}")
        print(f"  [P{idx:02d}] 第{rnd}轮 {'✓' if ok else '✗ ' + '; '.join(issues)[:150]}"
              f" ({time.time()-t0:.0f}s)", flush=True)
        ev(f"P{idx:02d} 第{rnd}轮 {'✓ 通过' if ok else '✗ 未过, 带问题重写'}"
           f" ({time.time()-t0:.0f}s)")
        if ok:
            return svg, []
        history = "\n".join(f"- {i}" for i in issues)
    return last_svg, issues   # 用尽轮次, 返回最后一稿 + 问题
