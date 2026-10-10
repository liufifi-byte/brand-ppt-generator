/* Brand PPT Generator 前端逻辑: 上传 → 轮询进度 → 下载。无框架, 无构建步骤。 */
(function () {
  const $ = (id) => document.getElementById(id);
  let file = null;
  let mode = "template";
  let pollTimer = null;
  let currentJob = null;
  let logSeen = 0;

  // ── 文件选择 (点击 + 拖拽 + 键盘) ──
  const drop = $("drop"), fileInput = $("file");
  drop.setAttribute("role", "button");
  drop.setAttribute("tabindex", "0");
  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
  });
  function setFile(f) {
    if (!f) return;
    if (!/\.(md|markdown|txt)$/i.test(f.name)) { alert("仅支持 .md / .markdown / .txt"); return; }
    file = f;
    $("fname").textContent = f.name;
    $("go").disabled = false;
  }

  // ── 模式选择 (radio 语义: 点击/方向键切换) ──
  const modeCards = Array.from(document.querySelectorAll(".mode"));
  function selectMode(el) {
    modeCards.forEach((m) => {
      m.classList.toggle("sel", m === el);
      m.setAttribute("aria-checked", m === el ? "true" : "false");
    });
    mode = el.dataset.mode;
  }
  modeCards.forEach((el) => el.addEventListener("click", () => selectMode(el)));
  document.querySelector(".modes").addEventListener("keydown", (e) => {
    const i = modeCards.findIndex((m) => m.classList.contains("sel"));
    if (e.key === "ArrowRight" && i < modeCards.length - 1) selectMode(modeCards[i + 1]);
    if (e.key === "ArrowLeft" && i > 0) selectMode(modeCards[i - 1]);
  });

  // ── 提交任务 ──
  $("go").addEventListener("click", async () => {
    if (!file) return;
    $("go").disabled = true;
    $("go").textContent = "上传中…";
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
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
      $("go").disabled = false;
      $("go").textContent = "生成 PPT";
    }
  });

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

    // 日志增量追加 (✓/✗ 着色)
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
        $("dlnote").textContent = job.file_name + " · " + job.mode + " 模式";
      }
      refreshJobs();
    }
  }

  // ── 历史任务 ──
  async function refreshJobs() {
    try {
      const r = await fetch("/api/jobs");
      const jobs = await r.json();
      const ul = $("jobs");
      ul.textContent = "";
      if (!jobs.length) {
        ul.innerHTML = '<li style="cursor:default;color:var(--dark)">暂无</li>';
        return;
      }
      const stZh = { queued: "排队", running: "生成中", done: "完成", failed: "失败" };
      for (const j of jobs.slice(0, 12)) {
        const li = document.createElement("li");
        const st = document.createElement("span");
        st.className = "st " + j.status; st.textContent = stZh[j.status] || j.status;
        const nm = document.createElement("span");
        nm.className = "jname"; nm.textContent = j.file_name + "（" + j.mode + "）";
        const tm = document.createElement("span");
        tm.className = "jtime"; tm.textContent = j.created.replace("T", " ");
        li.setAttribute("role", "button");
        li.setAttribute("tabindex", "0");
        li.append(st, nm, tm);
        li.addEventListener("click", () => {
          currentJob = j.id; logSeen = 0;
          $("progcard").style.display = "block";
          $("log").textContent = ""; $("dlrow").style.display = "none";
          startPoll();
          setProgress(j);
          window.scrollTo({ top: 0, behavior: "smooth" });
        });
        ul.appendChild(li);
      }
    } catch (e) { /* ignore */ }
  }
  refreshJobs();
})();
