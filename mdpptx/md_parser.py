"""md 周报解析: 模块 → 条目(标题/日期/段落)。

输入格式 (见 sample/input.md):
    __文档标题（MM/DD-MM/DD）__
    __模块名__
    无条目模块的正文段 (价格类模块)
    - __新闻标题__（YYYY/MM/DD）
    新闻第一段…
    新闻第二段…
"""
from __future__ import annotations
import re


def _unesc(s: str) -> str:
    return re.sub(r"\\([.\-,()\[\]!])", r"\1", s)


def parse_md(md_text: str) -> dict:
    lines = md_text.splitlines()
    doc_title, modules, cur_mod, cur_item = "", [], None, None
    for ln in lines:
        t = ln.strip()
        m = re.match(r"^__(.+?)__\s*$", t)
        if m and not t.startswith("- "):
            if not doc_title:
                doc_title = _unesc(m.group(1)); continue
            cur_mod = {"name": _unesc(m.group(1)), "items": []}
            modules.append(cur_mod); cur_item = None; continue
        if cur_mod is None:
            continue
        im = re.match(r"^-\s*__(.+?)__\s*[（(](\d{4}/\d{2}/\d{2})[)）]\s*$", t)
        if im:
            cur_item = {"title": _unesc(im.group(1)), "date": im.group(2), "paras": []}
            cur_mod["items"].append(cur_item); continue
        if t and not t.startswith("![") and cur_item is not None:
            cur_item["paras"].append(_unesc(t))
        elif t and cur_item is None and cur_mod["items"] == [] and not t.startswith("!["):
            # 无条目模块的正文段 (如价格动态)
            cur_mod.setdefault("paras", []).append(_unesc(t))
    return {"doc_title": doc_title,
            "modules": [m for m in modules if m.get("items") or m.get("paras")]}
