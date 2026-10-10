"""文档接入层: 任意文档 (md/txt/pdf/docx) → 结构化 input.md。

- .md/.txt: 直接作为 input.md (已是结构化格式)
- .pdf:     PyMuPDF 逐页提取文本
- .docx:    python-docx 段落 + 表格文本
- 之后非结构化文本经一次 LLM 调用转成管线格式 (文档标题/模块/条目),
  正文要求逐字保留; 结构不合法带错误反馈重试一次。

超长文档截断 (STRUCT_CHAR_LIMIT): v1 结构化调用只送前 N 字符, 日志明示。
"""
from __future__ import annotations
import re
from datetime import date
from pathlib import Path

STRUCT_CHAR_LIMIT = 14000

STRUCT_SYS = """你是文档结构整理器。把用户给的文档原文整理成固定的 Markdown 周报式结构, 供 PPT 生成管线消费。

输出格式 (只输出 Markdown 本身, 不要解释/围栏):
__文档标题（可选: 起止日期 MM/DD-MM/DD 或一句话主题）__

__模块一名称__

（无条目模块: 直接放正文段落, 每段一行）

__模块二名称__

- __条目标题__（YYYY/MM/DD）

条目第一段正文。

条目第二段正文。

硬规则:
1. 正文内容必须逐字来自原文: 不改写、不概括、不增删数字与单位; 超长段可原样保留。
2. 不编造原文没有的信息; 原文没有日期的条目用 __TODAY__ 提示的日期。
3. 按内容语义分模块 (3-6 个为宜), 模块名简短 (≤10 字)。
4. 条目标题取原文中该部分的主题句/首句关键信息 (≤30 字), 不虚构。
5. 有数据/价格类的段落优先归入一个无条目模块 (作为数据页素材)。
6. 文档标题取原文标题; 原文无标题则用一句话概括 (≤20 字)。"""


def extract_text(path: Path) -> str:
    """按扩展名提取纯文本。"""
    suf = path.suffix.lower()
    if suf in (".md", ".markdown", ".txt"):
        return path.read_text(encoding="utf-8")
    if suf == ".pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        try:
            parts = []
            for page in doc:
                parts.append(page.get_text("text"))
            return "\n\n".join(parts)
        finally:
            doc.close()
    if suf == ".docx":
        from docx import Document
        d = Document(str(path))
        parts = [p.text for p in d.paragraphs if (p.text or "").strip()]
        for tbl in d.tables:
            for row in tbl.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n\n".join(parts)
    raise ValueError(f"不支持的文件类型: {suf} (支持 md/txt/pdf/docx)")


def structure_with_llm(llm, text: str, today: str) -> str:
    """一次 LLM 调用: 原文 → 结构化 md。失败抛异常。"""
    if len(text) > STRUCT_CHAR_LIMIT:
        text = text[:STRUCT_CHAR_LIMIT] + "\n…(文档过长, 已截断)"
    user = f"__TODAY__={today}\n\n【文档原文】\n{text}"
    return llm._chat(STRUCT_SYS, user,
                     disable_thinking=True, temperature=0.1, timeout=360).strip()


def _structured_ok(md_text: str) -> bool:
    """结构化结果合法性: 有文档标题 + ≥1 个有内容模块。"""
    from .md_parser import parse_md
    try:
        doc = parse_md(md_text)
    except Exception:
        return False
    if not doc["doc_title"]:
        return False
    for m in doc["modules"]:
        if m.get("items") or m.get("paras"):
            return True
    return False


def prepare_input(work: Path, uploaded: Path, llm, on_event=None) -> str:
    """把上传文档转成 work/input.md, 返回使用的格式 ("structured-md"|"md")。

    md/txt 直接拷贝; 其他格式提取文本 + LLM 结构化 (失败带反馈重试一次)。
    """
    def ev(msg: str):
        if on_event:
            on_event("prep", msg)

    suf = uploaded.suffix.lower()
    if suf in (".md", ".markdown", ".txt"):
        (work / "input.md").write_text(uploaded.read_text(encoding="utf-8"),
                                       encoding="utf-8")
        ev("Markdown 文档直接接入")
        return "md"

    ev(f"提取 {suf.upper()} 文本…")
    text = extract_text(uploaded)
    if not text.strip():
        raise RuntimeError("文档中未提取到文本 (扫描件暂不支持)")
    ev(f"文本提取完成 ({len(text)} 字符), LLM 结构化中 (约 1-3 分钟)…")
    today = date.today().strftime("%Y/%m/%d")
    last_err = ""
    for attempt in (1, 2):
        md = structure_with_llm(llm, text, today)
        if _structured_ok(md):
            (work / "input.md").write_text(md, encoding="utf-8")
            ev("结构化完成" + (" (重试后成功)" if attempt == 2 else ""))
            return "structured-md"
        last_err = md[:200]
        ev(f"第 {attempt} 次结构化结果不合法, 重试…")
    raise RuntimeError(f"文档结构化失败 (输出不像结构化周报): {last_err}")
