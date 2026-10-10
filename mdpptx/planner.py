"""确定性页面规划: 文档 → 页面序列 (封面 / 数据页 / 每条新闻一页 / 结尾)。

规划不调模型 — 页数与页型完全由文档结构决定, 模型只负责每页的版面绘制。
"""
from __future__ import annotations


def plan_pages(doc: dict) -> list[dict]:
    pages = [{"type": "cover", "title": doc["doc_title"]}]
    for mod in doc["modules"]:
        if mod.get("paras"):            # 无条目模块 → 数据/价格页
            pages.append({"type": "price", "module": mod["name"], "paras": mod["paras"]})
            continue
        for it in mod["items"]:
            pages.append({"type": "news", "module": mod["name"], **it})
    pages.append({"type": "end"})
    return pages
