"""品牌主题配置 — 颜色/字体/装饰层/数据页文案全部集中于此。

换品牌 = 改这个文件 (或继承覆盖):
- colors/font: 品牌色板与字体栈
- decor / cover_decor: 装饰图层 SVG 片段 (引用 work/assets/ 下的品牌图片,
  由渲染后处理统一注入, 模型不画装饰 → 省输出 token 且全 deck 一致)
- price: 数据/价格页的标签与图表规格文案 (按你的业务素材改;
  extra_nums 是图表刻度等"素材外允许出现的数字"白名单)
- 版面几何坐标 (标题位置/卡片宽高等) 作为行业默认保留在 prompts 中,
  不属于品牌身份, 一般不用动。
"""
from __future__ import annotations

# 每页内容层之下统一叠加的装饰图 (href 相对 work/svg/ 目录解析)
DECOR = """<g id="decoration">
<image href="../assets/image1.png" x="-1" y="0" width="1282" height="721" preserveAspectRatio="xMidYMid meet"/>
<image href="../assets/image2.png" x="62" y="20" width="230" height="38" preserveAspectRatio="xMidYMid meet"/>
<image href="../assets/image3.png" x="1041" y="36" width="173" height="20" preserveAspectRatio="xMidYMid meet"/>
<image href="../assets/image4.png" x="50" y="671" width="104" height="9" preserveAspectRatio="xMidYMid meet"/>
</g>"""

# 封面专用装饰: 全幅背景 + 顶部标语条
COVER_DECOR = """<g id="decoration">
<image href="../assets/image5.jpeg" x="0" y="0" width="1280" height="720" preserveAspectRatio="xMidYMid meet"/>
<image href="../assets/image6.png" x="70" y="36" width="1160" height="38" preserveAspectRatio="xMidYMid meet"/>
</g>"""

THEME: dict = {
    "name": "示例品牌 · 蓝",

    "colors": {
        "primary": "#004A86",    # 主品牌色 (标题/KPI 数字/色条)
        "secondary": "#0069AC",  # 次品牌色
        "accent": "#00AAE8",     # 强调色 (分隔线/副题)
        "highlight": "#F7AB00",  # 亮点色 (虚线/高亮)
        "dark": "#4C4948",       # 深灰 (标签/页码)
        "body": "#1A1A1A",       # 正文
        "card_bg": "#F5F8FC",    # 卡片浅底
        "bar_bg": "#E8F1F8",     # 补充条浅蓝底
        "card_border": "#E8F1F8",
    },
    "font": "'SimHei','Arial',sans-serif",

    "decor": DECOR,
    "cover_decor": COVER_DECOR,
    "decor_min_imgs": 4,        # 内容页装饰图张数下限 (检查器用)
    "cover_min_imgs": 2,

    # 数据/价格页配置 (标签与图表规格文案按业务素材改)
    "price": {
        "kpi_labels": ["现货价格", "月度长期价格"],
        "kpi_values": ["8.65 万元/吨", "9.20 万元/吨"],   # 与素材数字一致
        "chart_title": "价格走势",
        # 图表规格 (写进提示词, 坐标级; 改刻度/日期时同步改 extra_nums)
        "chart_spec": (
            '右侧图表面板: <g id="chart"> 面板底 rect x=640 y=200 宽560 高280 '
            'fill=#F5F8FC rx=8;\n'
            '  标题「价格走势」x=658 y=228 font-size=22 fill=#004A86;\n'
            '  5条横网格线 x=660..1180 (stroke=#D8E2EC stroke-width=1), '
            'y=420/380/340/300/260 对应刻度 8.4/8.6/8.8/9.0/9.2 '
            '(刻度数字 font-size=16 fill=#4C4948 画在 x=632 右对齐);\n'
            '  现货折线: polyline points="680,403 1000,402" stroke=#00AAE8 '
            'stroke-width=3 fill=none; 两端圆点 r=5 fill=#00AAE8; '
            'x 轴标签「10/06」「10/10」在点下方 y=444;\n'
            '  月度长期价格虚线: line x1=660 x2=1180 y=260 stroke=#F7AB00 '
            'stroke-width=2 stroke-dasharray="8,6"; 右侧标签「9.20」'
            'font-size=16 fill=#F7AB00;\n'
            '  图例: 线段+文字「现货价格」「月度长期价格」font-size=16 在 y=470。'
        ),
        "source_line": "数据来源：市场公开数据整理",
        # 素材之外允许出现的数字 (图表刻度/坐标标签; 须为完整 token, 如 "8.4")
        "extra_nums": {"8.4", "8.6", "8.8", "9.0", "9.2", "10", "06"},
    },

    # 结尾页文案
    "end": {"main": "谢谢", "sub": "THANKS FOR WATCHING"},
}


def get_theme() -> dict:
    return THEME


# ── 任务级覆盖 (Web 上传 PPT 模板 → 提取主题色覆盖默认色板) ──
# 任务串行执行, 覆盖→生成→恢复; 各模块持有 THEME 同一引用, 原地改写即可生效

def apply_override(ov: dict) -> None:
    """原地合并覆盖 (ov: {"colors": {...}, "name": ...})。"""
    THEME["name"] = ov.get("name", THEME["name"])
    for k, v in (ov.get("colors") or {}).items():
        if k in THEME["colors"]:
            THEME["colors"][k] = v


def snapshot() -> dict:
    """深拷贝当前 THEME (恢复用)。"""
    import copy
    return copy.deepcopy(THEME)


def restore(snap: dict) -> None:
    """恢复到 snapshot 状态 (嵌套 dict 原地写回, 保持各模块引用有效)。"""
    for k, v in snap.items():
        if isinstance(v, dict) and isinstance(THEME.get(k), dict):
            THEME[k].clear()
            THEME[k].update(v)
        else:
            THEME[k] = v
