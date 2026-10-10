"""提示词构建 — system 版式规范 + 各页型的 user 提示。

设计要点:
- 版式规范坐标级写死在 SYS 里 (全 deck 各页一致, 模型无自由发挥空间)
- 颜色/字体从 theme 注入; 数据页文案与图表规格来自 theme.price
- 素材段落 verbatim 纪律 + 数字白名单与检查器 (checks) 同口径
"""
from __future__ import annotations
import re

from .theme import get_theme

T = get_theme()
C = T["colors"]


def build_sys() -> str:
    return f"""你是品牌周报 PPT 的 SVG 设计师。在 1280×720 画布上, 严格按【版式规范】写一页 SVG。

品牌色: 主色 {C['primary']} / 次色 {C['secondary']} / 强调 {C['accent']} / 亮点 {C['highlight']} / 深灰 {C['dark']} / 浅底 {C['card_bg']} / 浅色条 {C['bar_bg']}
字体: font-family="{T['font']}"

# 装饰图 (不用你画): 页面边框/顶部 logo 等装饰层由系统自动叠加, 你只画内容层

# 版式规范 (坐标级, 严格执行; 全 deck 各页保持一致)
- 页面标题: x=77 y=123 高51, font-size=34, font-weight=bold, fill={C['primary']}
- 内容卡: x=80 宽1120, fill=#FFFFFF 或 {C['card_bg']}, rx=8, 左侧 6px 竖条 rect fill={C['primary']} (卡同高)
- KPI 磁贴: 180×76, 浅底圆角; 数字 font-size=40 bold fill={C['primary']} 居中; 标签 font-size=20 fill={C['dark']} 居中
- 正文行: font-size=20, 行高27 (相邻 text 的 y 差=27), fill={C['body']}, x 从 110 或 378 起
- 补充条: x=110 y≈490 宽1060 高36, fill={C['bar_bg']}, rx=6, 内文 font-size=20 fill={C['primary']}
- 页码: x=1167 y=682, font-size=16, fill={C['dark']}, 格式「NN / TT」
- 标题下方细分隔线: rect x=80 宽1120 高2 fill={C['accent']} (仅新闻页)
- 所有内容元素必须画在 x∈[80,1200], y∈[100,660] 内; 底部横条类元素 x≥170 (避让左下标识)

# 内容纪律 (违反=废稿)
- 周报正文 verbatim: 素材段落一字不改放入, 超长段拆成多行 <text> (每行≤50个全角字符), 同一段的各行必须连续排列、中间不插入其他元素
- 所有数字必须逐字来自素材 (含单位写法一致, 如 6866tU 不写成 6866 tU); 素材里没有的数字绝不出现
- 封面不放任何数据/KPI
- 严禁输出: source: / docx [ / 源自 / 注： 等溯源标注 (数据页的「数据来源：…」除外)

# SVG 格式要求 (违反=废稿)
- 输出完整 SVG 文档, 含 <?xml version="1.0" encoding="UTF-8"?> 声明
- 属性值引号完整闭合; <g id="..."> 分组包裹逻辑块; 禁止 <animate>/foreignObject/script
- 只输出 SVG 代码, 不要 markdown 围栏、不要解释"""


def page_user(pg: dict, idx: int, total: int, doc: dict) -> tuple[str, list[str], set[str]]:
    """返回 (user prompt, verbatim 素材清单, 数字白名单附加项)。"""
    nn_tt = {"NN": str(idx), "TT": str(total)}
    base_extra = {str(idx), str(total)}
    t = pg["type"]
    if t == "cover":
        m = re.search(r"[（(](\d{2})/(\d{2})-(\d{2})/(\d{2})[)）]", doc["doc_title"])
        year = "2026"
        for mod in doc["modules"]:
            for it in mod.get("items", []):
                year = it["date"][:4]; break
            break
        period = (f"{year}年{int(m.group(1))}月{int(m.group(2))}日至"
                  f"{int(m.group(3))}月{int(m.group(4))}日") if m else ""
        srcs = [doc["doc_title"], period]
        usr = f"""这是封面页 (第{idx}/{total}页)。
版式: 两条水平分隔线 rect x=80 宽1120 高3 fill={C['primary']}, 分别在 y=300 与 y=600;
主标题「{doc['doc_title']}」x=80 y=360 font-size=52 bold fill={C['primary']};
副题行「{period}」x=80 y=440 font-size=30 fill={C['dark']}。
绝对不放任何数字/KPI/数据。页码右下「{idx} / {total}」。输出这一页的完整 SVG:"""
        return usr, srcs, base_extra | {year}
    if t == "price":
        paras = pg["paras"]
        p = T["price"]
        labels, values = p["kpi_labels"], p["kpi_values"]
        srcs = paras
        usr = f"""这是数据页 (第{idx}/{total}页), 模块「{pg['module']}」。
版式:
- 页面标题「{pg['module']}」(规范坐标);
- 左侧两张 KPI 卡 (x=80 宽520): 第一张 y=200 高130 标签「{labels[0]}」+ 大数字「{values[0]}」(font-size=32 bold) + 两行说明(素材第1段的原文, font-size=18 行高25, x=94);
  第二张 y=350 高130 标签「{labels[1]}」+ 大数字「{values[1]}」+ 两行说明(素材第2段原文);
  卡片顶部色头条 rect 高36 fill={C['primary']} 圆角, 标签白字放条内; 卡底 4px 强调色线。
{p['chart_spec']}
- 底部分隔线 x=170 宽1030 y=520 + 「{p['source_line']}」font-size=16 fill={C['dark']}。
素材 (两段原文, 逐字放入卡片说明行):
{chr(10).join(paras)}
页码「{idx} / {total}」。输出这一页的完整 SVG:"""
        return usr, srcs, base_extra | set(p["extra_nums"])
    if t == "news":
        title, date, paras = pg["title"], pg["date"], pg["paras"]
        sub = f"{date[:4]}年{int(date[5:7])}月{int(date[8:])}日 ｜ {pg['module']}"
        srcs = [title, sub] + paras
        usr = f"""这是新闻详情页 (第{idx}/{total}页)。
- 页面标题:「{pg['module']}：{title}」(规范坐标, 一行放不下可缩至 font-size=28);
- 标题下细分隔线;
- 副题行「{sub}」x=80 y=170 font-size=20 fill={C['accent']};
- 内容卡 y=200 高~170: 从素材段落里挑 1-3 个关键数字做 KPI 磁贴 (180×76, 横排在卡内左侧 x=110/310/510), 右侧放第一段正文 (逐字, 拆行 x=720 宽~460);
- 内容卡 y=390 高~150: 放第二段正文 (逐字拆行, x=110 宽~1000);
- 补充条 y=560: 从素材中取一句关键事实, 前缀「补充：」, font-size=20。
素材 (全部逐字使用, 数字一字不改):
【标题】{title}（{date}）
【第一段】{paras[0] if paras else ''}
【第二段】{paras[1] if len(paras) > 1 else '（无第二段, 此卡改放第一段剩余部分）'}
页码「{idx} / {total}」。输出这一页的完整 SVG:"""
        return usr, srcs, base_extra
    # end
    e = T["end"]
    usr = f"""这是结尾页 (第{idx}/{total}页)。
版式: 居中大字「{e['main']}」font-size=72 bold fill={C['primary']} (x=640 y=380 text-anchor=middle);
下方「{e['sub']}」font-size=20 fill={C['dark']} letter-spacing=4 居中。
页码「{idx} / {total}」。输出这一页的完整 SVG:"""
    return usr, [], base_extra
