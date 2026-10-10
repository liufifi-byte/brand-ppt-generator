"""Web 服务: 上传 Markdown 周报 → 后台生成品牌 PPT → 下载 PPTX。

任务模型 (内存, 单进程):
    POST /api/jobs          上传 md + 模式 (template/generate) → 建任务, 后台线程跑管线
    GET  /api/jobs/{id}     轮询进度 (phase/msg/页进度/日志尾部)
    GET  /api/jobs/{id}/download  下载生成的 pptx
    GET  /api/jobs          任务列表

同时只跑一个任务 (全局串行锁): 并行多任务会撞模型账户吞吐, 429 重试
会成倍拉长所有任务 (实测教训), 排队更稳。
"""
from __future__ import annotations
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .llm import LLMClient

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "sample"
JOBS_DIR = REPO_ROOT / "work" / "jobs"
WEB_DIR = REPO_ROOT / "web"

router = APIRouter()

# 内存任务表 (单进程; 重启即清)
_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_run_lock = threading.Lock()   # 全局串行: 同时只跑一个生成任务
_LOG_KEEP = 60                 # 任务里保留的日志行数


def _llm_factory(model: str | None) -> LLMClient:
    return LLMClient(model)


def _update(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        log_line = fields.pop("log_line", None)
        if log_line is not None:
            job["log"].append(log_line)
            job["log"] = job["log"][-_LOG_KEEP:]
        job.update(fields)


def _on_event(job_id: str):
    def ev(phase: str, msg: str, **kw):
        _update(job_id, phase=phase, msg=msg,
                log_line=f"[{phase}] {msg}",
                **{k: v for k, v in kw.items()
                   if k in ("pages_done", "pages_total")})
    return ev


def _run_job(job_id: str) -> None:
    from . import theme
    job = _jobs[job_id]
    work = Path(job["work_dir"])
    out = work / f"{job_id}.pptx"
    # 串行锁: 等前面任务跑完 (排队中)
    with _run_lock:
        _update(job_id, status="running", phase="queued",
                msg="排队中 (同时只跑一个任务)" if job.get("queued_behind") else "启动中")
        theme_snap = theme.snapshot()
        try:
            # 1. 文档接入: 任意格式 → input.md (md 直传; pdf/docx 提取+LLM 结构化)
            from .ingest import prepare_input
            prepare_input(work, work / "upload" / job["file_name"],
                          _llm_factory(None), on_event=_on_event(job_id))
            # 2. 上传模板 → 主题色覆盖 (v1: 仅色板)
            tpl = work / "template.pptx"
            if tpl.exists():
                from .template_pptx import extract_theme_override
                ov = extract_theme_override(tpl)
                if ov:
                    theme.apply_override(ov)
                    _update(job_id, log_line="[template] 模板主题色已应用: "
                            + " ".join(ov["colors"].values()))
                else:
                    _update(job_id, log_line="[template] 模板未解析到主题色, 用默认色板")
            # 3. 生成 (模板快速模式)
            from .template_mode import run_template
            run_template(work, out, None, _llm_factory, on_event=_on_event(job_id))
            if not out.exists():
                raise RuntimeError("PPTX 未生成 (见日志)")
            _update(job_id, status="done", phase="done",
                    msg="生成完成", pptx_ready=True)
        except Exception as e:   # noqa: BLE001
            _update(job_id, status="failed", phase="failed",
                    error=str(e)[:500], msg=f"失败: {str(e)[:200]}",
                    log_line=f"[failed] {str(e)[:300]}")
        finally:
            theme.restore(theme_snap)


ALLOWED_DOC_EXTS = (".md", ".markdown", ".txt", ".pdf", ".docx")


@router.post("/api/jobs")
async def create_job(file: UploadFile = File(...),
                     template: UploadFile = File(None)):
    name = file.filename or ""
    if not name.lower().endswith(ALLOWED_DOC_EXTS):
        raise HTTPException(400, "支持的文档格式: md / txt / pdf / docx")
    content = await file.read()
    if not content.strip():
        raise HTTPException(400, "文件为空")
    tpl_name = ""
    tpl_bytes = b""
    if template and template.filename:
        if not template.filename.lower().endswith(".pptx"):
            raise HTTPException(400, "模板仅支持 .pptx 格式")
        tpl_name = template.filename
        tpl_bytes = await template.read()

    job_id = uuid.uuid4().hex[:10]
    work = JOBS_DIR / job_id
    (work / "svg").mkdir(parents=True, exist_ok=True)
    (work / "upload").mkdir(exist_ok=True)
    # 原始上传件存 upload/ (ingest 按扩展名处理)
    (work / "upload" / name).write_bytes(content)
    if tpl_bytes:
        (work / "template.pptx").write_bytes(tpl_bytes)
    # 品牌资产: 每个任务独立拷贝一份 (换品牌=替换 sample/assets)
    shutil.copytree(SAMPLE / "assets", work / "assets", dirs_exist_ok=True)

    with _lock:
        queued_behind = any(j["status"] in ("queued", "running") for j in _jobs.values())
        _jobs[job_id] = {
            "id": job_id, "mode": "template",
            "template_name": tpl_name, "file_name": name,
            "created": datetime.now().isoformat(timespec="seconds"),
            "status": "queued", "phase": "queued", "msg": "已排队",
            "pages_done": 0, "pages_total": 0,
            "log": [f"[upload] {name}"],
            "work_dir": str(work), "pptx_ready": False, "error": "",
            "queued_behind": queued_behind,
        }
    _jobs[job_id]["log"].append(
        f"[upload] 模板: {tpl_name}" if tpl_name else "[upload] 使用默认模板")
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return {"id": job_id, "status": "queued", "mode": "template",
            "template": tpl_name}


@router.get("/api/jobs")
def list_jobs():
    with _lock:
        items = sorted(_jobs.values(), key=lambda j: j["created"], reverse=True)
        return [{k: v for k, v in j.items() if k != "work_dir"} for j in items]


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在")
        return {k: v for k, v in job.items() if k != "work_dir"}


@router.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if not job.get("pptx_ready"):
        raise HTTPException(404, "PPTX 尚未生成")
    path = Path(job["work_dir"]) / f"{job_id}.pptx"
    if not path.exists():
        raise HTTPException(404, "PPTX 文件不存在")
    stem = Path(job["file_name"]).stem
    return FileResponse(path,
                        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename=f"{stem}_品牌PPT.pptx",
                        headers={"Cache-Control": "no-store"})


app = FastAPI(title="Brand PPT Generator", version="1.1.0")
app.include_router(router)
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
