# Brand PPT Generator — Markdown 周报 → 品牌 PPT

把一份结构化的 Markdown 周报变成**带品牌版式的 PPTX**：封面 / 数据页 / 每条新闻一页 / 结尾页，品牌色、logo 装饰层、页码规范全部自动套用，最终导出可直接使用的 `.pptx`。

两种生成模式：

| 模式 | 原理 | 速度 | 适用 |
|------|------|------|------|
| **模板快速模式** `template` | 版式由 Python 按母版坐标程序化渲染，模型只做一次批量 KPI 抽取（JSON 小调用） | 全 deck 分钟级 | 周报等结构固定的周期性产出 |
| **SVG 生成模式** `generate` | 逐页让 LLM 按坐标级版式规范画 SVG，过检查链，未过带问题清单重写（≤3 轮） | 单页 15s~5min | 版式需要模型灵活排布的页面 |

## 核心机制：程序化检查-修复环

模型输出不直接采用，每页 SVG 必须过五道检查，未通过则把**机器可读的问题清单**拼回提示词重写：

1. **XML 合法性** — 解析失败即废稿
2. **清洁检查** — 溯源标注（`source:` / `注：`等）、占位色、导出不支持的标签（`animate`/`foreignObject`）
3. **装饰完整性** — 品牌装饰图（边框/logo）必须完整回放
4. **verbatim 数字纪律** — 素材段落逐字命中；SVG 中出现的任何数字必须 ∈ 素材数字 ∪ 白名单（防模型编数）
5. **渲染像素检查** — cairosvg 实渲成 PNG，非白占比过低（白页）/过高（大面积色块遮蔽）都判失败

正文的数字串（含小数点/千分位/%）在折行时是**原子单位**，严禁从中间断开；页码、标题字号、卡片几何全部按母版坐标锁定。

## 快速开始

### 方式一：Web 界面（推荐）

```bash
pip install -r requirements.txt
cp .env.example .env        # 填 GLM_API_KEY
python -m mdpptx serve      # 打开 http://127.0.0.1:8020
```

网页上拖入文档（md / txt / **pdf / docx**，任意内容均可——非 Markdown 文档会先提取文本并自动结构化）→ 选模版（默认模版，或上传自己的 .pptx 提取主题色）→ 点「生成 PPT」→ 实时看检查日志 → 下载 .pptx。

### 方式二：命令行

```bash
python -m mdpptx init                     # work/ ← sample/ (示例周报+占位品牌图)
python -m mdpptx template --out demo.pptx # 模板模式: 分钟级全 deck
python -m mdpptx generate --pages 3       # 或 SVG 模式试点前 3 页
python -m mdpptx generate --full --out demo2.pptx
```

产物：`work/svg/page_NN.svg`（每页矢量稿）、`work/png/`（检查渲染预览）、`demo.pptx`。

> macOS 上 cairosvg 需要 cairo 库：`brew install cairo`，且运行前设置
> `export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`（Intel 机器路径为 `/usr/local/lib`）。
>
> 模型支持任何 OpenAI 兼容端点（`GLM_BASE_URL` 指向私有化部署即可）。推荐 `glm-5.3-flash`：
> 单页 SVG 生成 15s~5min，"始终思考"档在大 prompt 上单页可能到 280s+，管线默认 360s 调用超时。

## 输入

**网页**：md / txt / pdf / docx。PDF 与 Word 会先提取文本，再经一次 LLM 结构化调用转成管线格式（正文逐字保留纪律；超长文档默认截断前 1.4 万字符，见 `mdpptx/ingest.py`）。扫描件（纯图片 PDF）暂不支持。

**PPT 模版**：上传 .pptx 后自动提取主题色（accent1-4/dk2 → 生成色板），装饰版式仍用内置母版。v1 仅取色，模版图片/版式克隆在路线图上。

**命令行**输入仍是结构化 Markdown（`work/input.md`，格式如下）：

```markdown
__第N期某某周报（10/06-10/10）__      ← 文档标题 (含起止日期, 封面副题用)

__市场价格动态__                       ← 无条目模块 → 数据/价格页 (正文段落)

10月6日，现货价格为8.65万元/吨…

__行业动态__                           ← 有条目模块 → 每条新闻一页

- __新闻标题__（2026/10/08）          ← 条目: 标题 + 日期

新闻第一段…

新闻第二段…
```

## 换成你的品牌

1. **品牌图片**：替换 `work/assets/image1~6`（image1=内容页边框底图、2/3=顶部标识、4=底部细条、5=封面全幅背景、6=封面标语条）
2. **品牌配置**：改 `mdpptx/theme.py` — 色板、字体栈、装饰层 SVG 片段、数据页 KPI 标签与图表规格
3 版面几何坐标（标题位置/卡片宽度等）作为行业默认保留在提示词中，一般无需改动

## 架构

```
mdpptx/
├── server.py        Web 服务 (FastAPI): 上传任务/进度轮询/pptx 下载, 同时只跑一个任务
├── ingest.py        文档接入: pdf/docx 文本提取 + LLM 结构化 → input.md
├── template_pptx.py PPT 模版主题色提取 (.pptx clrScheme → 色板覆盖)
├── cli.py           统一入口 (serve / init / generate / template)
├── runner.py        SVG 生成模式编排 (CLI 与 Web 共用, on_event 进度回调)
├── md_parser.py     Markdown 周报解析 → 模块/条目/段落
├── planner.py       确定性页面规划 (不调模型: 封面/数据/新闻/结尾)
├── prompts.py       坐标级版式规范 system prompt + 各页型 user prompt
├── render.py        输出后处理 (装饰注入/清险) + 生成-检查-修复环
├── checks.py        五道检查器 (问题清单可直接拼回提示词)
├── template_mode.py 模板快速模式 (程序化渲染 + 1 次批量 KPI 调用)
├── llm.py           智谱云/OpenAI 兼容客户端 (JWT/退避/重试)
└── exporter.py      SVG → PPTX 导出
web/                 前端单页 (无构建步骤: 原生 HTML/JS)
converter/           vendored svg_to_pptx 转换器 (矢量 SVG → 原生 PPTX 形状)
sample/              示例周报 + 占位品牌图
tests/               单元测试 (不调 LLM)
```

## 运行测试

```bash
pytest
```

## 说明

- 周期性产出推荐固定用 `template` 模式：版式零漂移、成本一次小调用；`generate` 模式适合需要模型排布的页面（数据页图表等），两种模式可混用（模板模式对无母版的页型自动回落到模型生成）。
- `work/` 目录是运行产物（svg/png/缓存），已在 .gitignore 中。
- KPI 抽取结果缓存在 `work/kpi_cache.json`，重跑不重复调用；换素材后删除该文件。
