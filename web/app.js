/* Brand PPT Generator 前端逻辑 (v3): 上传文档+可选模版 → 轮询进度 → 下载。 */
(function () {
  const $ = (id) => document.getElementById(id);
  let file = null;          // 上传的文档
  let tplFile = null;       // 上传的 pptx 模版 (可空)
  let tplSource = "default"; // default | upload
  let pollTimer = null;
  let currentJob = null;
  let logSeen = 0;

  // ── 文档上传框 (点击/拖拽/键盘) ──
  const drop = $("drop"), fileInput = $("file");
  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
  });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
  function setFile(f) {
    if (!f) return;
    if (!/\.(md|markdown|txt|pdf|docx)$/i.test(f.name)) {
      alert("支持的文档格式: md / txt / pdf / docx"); return;
    }
    file = f;
    $("fname").textContent = f.name;
    $("fhint").textContent = "支持 pdf、word · 点击重新选择";
  }

  // ── 模版来源选择 (radio 语义) ──
  const opts = [$("tpl-default"), $("tpl-upload")];
  function selectOpt(el) {
    tplSource = el.id === "tpl-upload" ? "upload" : "default";
    opts.forEach((o) => {
      o.classList.toggle("sel", o === el);
      o.setAttribute("aria-checked", o === el ? "true" : "false");
    });
    // 上传模版组的生成按钮: 选了模版文件才出现
    $("go2").style.display = (tplSource === "upload" && tplFile) ? "" : "none";
  }
  opts.forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest("button.act")) return; // 组内按钮不触发改选
      selectOpt(el);
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectOpt(el); }
    });
  });
  $("addtpl").addEventListener("click", (e) => {
    e.stopPropagation();
    $("tplfile").click();
  });
  $("tplfile").addEventListener("change", () => {
    const f = $("tplfile").files[0];
    if (!f) return;
    if (!/\.pptx$/i.test(f.name)) { alert("模版仅支持 .pptx 格式"); return; }
    tplFile = f;
    selectOpt($("tpl-upload"));
    $("tpl-note").innerHTML = '已选模版: <span class="tname"></span>';
    $("tpl-note").querySelector(".tname").textContent = f.name;
  });

  // ── 提交 ──
  async function submit(btn) {
    if (!file) { alert("请先上传文档"); return; }
    if (tplSource === "upload" && !tplFile) { alert("请先添加 PPT 模版 (或选默认模版)"); return; }
    btn.disabled = true; btn.textContent = "提交中…";
    const form = new FormData();
    form.append("file", file);
    if (tplSource === "upload" && tplFile) form.append("template", tplFile);
    try {
      const r = await fetch("/api/jobs", { method: "POST", body: form });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        throw new Error(e.detail || r.statusText);
      }
      const job = await r.json();
      currentJob = job.id;
      logSeen = 0;
      $("progcard").style.display = "block";
      $("log").textContent = "";
      $("dlrow").style.display = "none";
      setProgress({ status: "queued", msg: "已提交, 排队中…" });
      startPoll();
      refreshJobs();
    } catch (e) {
      alert("提交失败: " + e.message);
    } finally {
      btn.disabled = false; btn.textContent = "生成 PPT";
    }
  }
  $("go").addEventListener("click", () => submit($("go")));
  $("go2").addEventListener("click", () => submit($("go2")));

  // ── 进度轮询 ──
  function startPoll() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!currentJob) return;
      try {
        const r = await fetch("/api/jobs/" + currentJob);
        if (!r.ok) throw new Error();
        setProgress(await r.json());
      } catch (e) { /* 单次失败忽略 */ }
    }, 2000);
  }
  function stopPoll() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

  function setProgress(job) {
    const stMap = { queued: "排队中…", running: "生成中…" };
    const done = job.status === "done", failed = job.status === "failed";
    $("strow").className = "status-row " + (job.status === "running" ? "running" : "");
    $("sttext").textContent = failed ? "生成失败"
      : done ? "生成完成 ✓" : (stMap[job.status] || "") + " " + (job.msg || "");
    const pct = job.pages_total > 0
      ? Math.round((job.pages_done / job.pages_total) * 100) : 0;
    $("barfill").style.width = (done ? 100 : pct) + "%";
    $("stpages").textContent = job.pages_total > 0
      ? job.pages_done + " / " + job.pages_total + " 页" : "";

    const logEl = $("log");
    if (job.log && job.log.length > logSeen) {
      const frag = document.createDocumentFragment();
      for (const line of job.log.slice(logSeen)) {
        const div = document.createElement("div");
        div.textContent = line;
        if (/✓|完成|通过/.test(line)) div.className = "ok";
        else if (/✗|失败|缺页/.test(line)) div.className = "bad";
        frag.appendChild(div);
      }
      logEl.appendChild(frag);
      logSeen = job.log.length;
      logEl.scrollTop = logEl.scrollHeight;
    }
    if (done || failed) {
      stopPoll();
      if (done) {
        $("dlrow").style.display = "flex";
        $("dllink").href = "/api/jobs/" + job.id + "/download";
        $("dlnote").textContent = job.file_name +
          (job.template_name ? " · 模版: " + job.template_name : "");
      }
      refreshJobs();
    }
  }

  // ── 历史任务 (左侧栏) ──
  async function refreshJobs() {
    try {
      const r = await fetch("/api/jobs");
      const jobs = await r.json();
      const ul = $("jobs");
      ul.textContent = "";
      if (!jobs.length) {
        ul.innerHTML = '<li class="empty" style="cursor:default">暂无</li>';
        return;
      }
      const stZh = { queued: "排队", running: "生成中", done: "完成", failed: "失败" };
      for (const j of jobs.slice(0, 15)) {
        const li = document.createElement("li");
        li.setAttribute("role", "button");
        li.setAttribute("tabindex", "0");
        const row = document.createElement("div");
        row.className = "row1";
        const st = document.createElement("span");
        st.className = "st " + j.status; st.textContent = stZh[j.status] || j.status;
        const nm = document.createElement("span");
        nm.className = "jname"; nm.textContent = j.file_name;
        row.append(st, nm);
        const tm = document.createElement("span");
        tm.className = "jtime";
        tm.textContent = j.created.replace("T", " ") +
          (j.template_name ? " · 有模版" : "");
        li.append(row, tm);
        li.addEventListener("click", () => {
          currentJob = j.id; logSeen = 0;
          $("progcard").style.display = "block";
          $("log").textContent = ""; $("dlrow").style.display = "none";
          startPoll();
          setProgress(j);
        });
        ul.appendChild(li);
      }
    } catch (e) { /* ignore */ }
  }
  refreshJobs();
})();
