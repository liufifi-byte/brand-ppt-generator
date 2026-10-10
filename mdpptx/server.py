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
    job = _jobs[job_id]
    work = Path(job["work_dir"])
    out = work / f"{job_id}.pptx"
    # 串行锁: 等前面任务跑完 (排队中)
    with _run_lock:
        _update(job_id, status="running", phase="queued",
                msg="排队中 (同时只跑一个任务)" if job.get("queued_behind") else "启动中")
        try:
            if job["mode"] == "template":
                from .template_mode import run_template
                run_template(work, out, None, _llm_factory, on_event=_on_event(job_id))
            else:
                from .runner import run_generate
                run_generate(work, out, None, 2, _llm_factory,
                             on_event=_on_event(job_id))
            if not out.exists():
                raise RuntimeError("PPTX 未生成 (见日志)")
            _update(job_id, status="done", phase="done",
                    msg="生成完成", pptx_ready=True)
        except Exception as e:   # noqa: BLE001
            _update(job_id, status="failed", phase="failed",
                    error=str(e)[:500], msg=f"失败: {str(e)[:200]}",
                    log_line=f"[failed] {str(e)[:300]}")


@router.post("/api/jobs")
async def create_job(file: UploadFile = File(...),
                     mode: str = Form("template")):
    if mode not in ("template", "generate"):
        raise HTTPException(400, "mode 仅支持 template / generate")
    name = file.filename or ""
    if not name.lower().endswith((".md", ".markdown", ".txt")):
        raise HTTPException(400, "仅支持 .md / .markdown / .txt 格式 (格式见 README)")
    content = await file.read()
    if not content.strip():
        raise HTTPException(400, "文件为空")

    job_id = uuid.uuid4().hex[:10]
    work = JOBS_DIR / job_id
    (work / "svg").mkdir(parents=True, exist_ok=True)
    # 品牌资产: 每个任务独立拷贝一份 (换品牌=替换 sample/assets)
    shutil.copytree(SAMPLE / "assets", work / "assets", dirs_exist_ok=True)
    (work / "input.md").write_bytes(content)

    with _lock:
        queued_behind = any(j["status"] in ("queued", "running") for j in _jobs.values())
        _jobs[job_id] = {
            "id": job_id, "mode": mode, "file_name": name,
            "created": datetime.now().isoformat(timespec="seconds"),
            "status": "queued", "phase": "queued", "msg": "已排队",
            "pages_done": 0, "pages_total": 0,
            "log": [f"[upload] {name} · 模式: {mode}"],
            "work_dir": str(work), "pptx_ready": False, "error": "",
            "queued_behind": queued_behind,
        }
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return {"id": job_id, "status": "queued", "mode": mode}


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
