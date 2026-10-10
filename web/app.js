/* Brand PPT 前端 v4 — 上传内容文档 → 选模板 → 生成 PPT → 下载。
   状态模型: 文档(空/已选/错误) · 模板(品牌蓝/自定义: 上传中/已就绪/失败) · 任务(排队/生成中/成功/失败) */
(function () {
  const $ = (id) => document.getElementById(id);
  const DOC_EXTS = /\.(md|markdown|txt|pdf|docx)$/i;

  const state = {
    doc: null,          // {file} | null
    docErr: "",
    tplSource: "brand", // brand | custom
    tpl: null,          // {file, uploading, colors, readable, err}
    job: null,          // 当前展示的任务 id
    submitting: false,
    logSeen: 0,
    pollTimer: null,
  };

  // ── 工具 ──
  function fmtSize(n) {
    if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
    if (n >= 1024) return Math.round(n / 1024) + " KB";
    return n + " B";
  }

  // ── 内容文档区: 空 / 已选 / 错误 三态 ──
  const zone = $("dropzone"), fileInput = $("file");
  function renderDocZone() {
    zone.classList.remove("has-file", "err");
    zone.innerHTML = "";
    function buildEmpty() {
      const d = document.createElement("div");
      d.style.display = "contents";
      d.innerHTML = `
        <svg class="ic" viewBox="0 0 24 24"><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/></svg>
        <div class="t1">点击上传或拖拽文件至此</div>
        <div class="t2">支持 PDF、Word（也接受 Markdown / TXT）</div>`;
      return d;
    }
    if (state.docErr) {
      zone.classList.add("err");
      const b = document.createElement("div");
      b.className = "err-body";
      b.innerHTML = `<svg class="ic" viewBox="0 0 24 24" style="font-size:24px;color:var(--err)"><path d="M12 9v4"/><path d="M12 17h.01"/><circle cx="12" cy="12" r="10"/></svg>
        <div class="msg"></div>`;
      b.querySelector(".msg").textContent = state.docErr;
      const retry = document.createElement("button");
      retry.className = "link-btn"; retry.textContent = "重新选择文件";
      retry.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
      b.appendChild(retry);
      zone.appendChild(b);
      return;
    }
    if (!state.doc) { zone.appendChild(buildEmpty()); return; }
    zone.classList.add("has-file");
    const f = state.doc.file;
    const row = document.createElement("div");
    row.className = "file-info";
    row.innerHTML = `
      <svg class="ic" viewBox="0 0 24 24"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>
      <div class="meta"><div class="fname"></div><div class="fsize"></div></div>
      <button class="link-btn" title="更换文件">更换</button>
      <button class="icon-btn" title="删除文件">
        <svg class="ic" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
      </button>`;
    row.querySelector(".fname").textContent = f.name;
    row.querySelector(".fname").title = f.name;
    row.querySelector(".fsize").textContent = fmtSize(f.size);
    row.querySelector(".link-btn").addEventListener("click", (e) => {
      e.stopPropagation(); fileInput.click();
    });
    row.querySelector(".icon-btn").addEventListener("click", (e) => {
      e.stopPropagation(); state.doc = null; fileInput.value = "";
      renderDocZone(); updateActionRow();
    });
    zone.appendChild(row);
  }
  function setDoc(f) {
    state.docErr = "";
    if (!f) { state.doc = null; }
    else if (!DOC_EXTS.test(f.name)) state.docErr = "不支持的格式：" + f.name + "（支持 PDF、Word、Markdown、TXT）";
    else if (f.size === 0) state.docErr = "文件为空，请重新选择";
    else state.doc = { file: f };
    renderDocZone();
    updateActionRow();
  }
  zone.addEventListener("click", () => { if (!state.doc && !state.docErr) fileInput.click(); });
  zone.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !state.doc && !state.docErr) {
      e.preventDefault(); fileInput.click();
    }
  });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.style.borderColor = "var(--brand)"; });
  zone.addEventListener("dragleave", () => { zone.style.borderColor = ""; });
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); zone.style.borderColor = "";
    if (e.dataTransfer.files.length) setDoc(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => setDoc(fileInput.files[0]));

  // ── 模板区 ──
  const tplInput = $("tplfile");
  function selectTpl(which) {
    state.tplSource = which;
    const brand = which === "brand";
    $("tplBrand").classList.toggle("sel", brand);
    $("tplBrand").setAttribute("aria-checked", brand ? "true" : "false");
    $("tplCustom").classList.toggle("sel", !brand);
    $("tplCustom").setAttribute("aria-checked", brand ? "false" : "true");
    updateActionRow();
  }
  $("tplBrand").addEventListener("click", () => selectTpl("brand"));
  $("tplCustom").addEventListener("click", () => {
    if (!state.tpl) { tplInput.click(); return; }   // 空槽位点击 = 选文件
    selectTpl("custom");
  });
  $("tplCustom").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!state.tpl) tplInput.click(); else selectTpl("custom");
    }
  });

  tplInput.addEventListener("change", () => {
    const f = tplInput.files[0];
    if (!f) return;
    if (!/\.pptx$/i.test(f.name)) {
      renderTplErr("模板仅支持 .pptx 格式，请重新选择");
      return;
    }
    state.tpl = { file: f, uploading: true, colors: null, readable: null, err: "" };
    renderTplErr("");
    renderCustomTpl();
    uploadTplPreview(f);
  });

  function renderTplErr(msg) {
    const el = $("tplErr");
    el.style.display = msg ? "" : "none";
    el.textContent = msg;
  }

  function renderCustomTpl() {
    const pv = $("customPreview");
    pv.querySelectorAll(".tpl-empty,.tpl-uploaded").forEach((n) => n.remove());
    const t = state.tpl;
    if (!t) return;
    if (t.uploading) {
      const d = document.createElement("div");
      d.className = "tpl-empty loading";
      d.innerHTML = `<span class="spin"></span><div class="t">正在读取模板主题色…</div>`;
      pv.appendChild(d);
      return;
    }
    const d = document.createElement("div");
    d.className = "tpl-uploaded";
    // 主题色 swatch 预览 (后端只提取颜色 — 如实展示, 不伪造版式缩略图)
    if (t.readable && t.colors && Object.keys(t.colors).length) {
      const sw = document.createElement("div");
      sw.className = "swatches";
      for (const c of Object.values(t.colors)) {
        const i = document.createElement("i");
        i.style.background = c; i.title = c;
        sw.appendChild(i);
      }
      d.appendChild(sw);
    }
    const chip = document.createElement("div");
    chip.className = "file-chip";
    chip.innerHTML = `
      <svg class="ic" style="color:var(--brand)" viewBox="0 0 24 24"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg>
      <span class="n"></span>
      <button class="link-btn" title="更换模板" style="padding:3px 6px;font-size:12px">更换</button>
      <button class="icon-btn" title="删除模板" style="padding:3px">
        <svg class="ic" viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
      </button>`;
    chip.querySelector(".n").textContent = t.file.name;
    chip.querySelector(".n").title = t.file.name;
    chip.querySelector(".link-btn").addEventListener("click", (e) => {
      e.stopPropagation(); tplInput.click();
    });
    chip.querySelector(".icon-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      state.tpl = null; tplInput.value = "";
      renderCustomTpl(); renderTplErr("");
      resetCustomTplMeta();
      if (state.tplSource === "custom") selectTpl("brand");
      updateActionRow();
    });
    d.appendChild(chip);
    pv.appendChild(d);
    // 说明文案按真实能力
    $("customName").textContent = t.readable && t.colors && Object.keys(t.colors).length
      ? "自定义模板（主题色）" : "自定义模板";
    $("customDesc").textContent = t.readable && t.colors && Object.keys(t.colors).length
      ? "已读取模板配色 " + Object.keys(t.colors).length + " 色，生成时应用"
      : (t.err || "未读取到主题色，生成时将使用默认配色");
  }
  function resetCustomTplMeta() {
    $("customName").textContent = "上传自定义模板";
    $("customDesc").textContent = ".pptx — 生成时读取模板主题色应用于配色";
  }

  async function uploadTplPreview(f) {
    try {
      const form = new FormData();
      form.append("template", f);
      const r = await fetch("/api/template-preview", { method: "POST", body: form });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        throw new Error(e.detail || r.statusText);
      }
      const data = await r.json();
      state.tpl.uploading = false;
      state.tpl.readable = !!data.readable;
      state.tpl.colors = data.colors || {};
      state.tpl.err = data.readable ? "" : "模板内未解析到主题色";
      renderCustomTpl();
      selectTpl("custom");
      updateActionRow();
    } catch (e) {
      state.tpl.uploading = false;
      state.tpl.readable = false;
      state.tpl.err = "模板读取失败：" + e.message;
      renderCustomTpl();
      renderTplErr(state.tpl.err);
      updateActionRow();
    }
  }

  // ── 主操作行 ──
  function updateActionRow() {
    const tplName = state.tplSource === "brand" ? "品牌蓝"
      : (state.tpl && !state.tpl.uploading ? "自定义模板" : "自定义模板（读取中）");
    $("selStatus").textContent = "已选择：" + tplName +
      (state.doc ? " · 文档：" + state.doc.file.name : "");
    const can = !!state.doc && !state.submitting &&
      !(state.tplSource === "custom" && (!state.tpl || state.tpl.uploading));
    $("go").disabled = !can;
  }

  async function submit() {
    if (!state.doc || state.submitting) return;
    state.submitting = true;
    $("go").classList.add("loading");
    $("goText").textContent = "正在生成…";
    updateActionRow();
    const form = new FormData();
    form.append("file", state.doc.file);
    if (state.tplSource === "custom" && state.tpl) form.append("template", state.tpl.file);
    try {
      const r = await fetch("/api/jobs", { method: "POST", body: form });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        throw new Error(e.detail || r.statusText);
      }
      const job = await r.json();
      bindJob(job.id, true);
      refreshJobs();
    } catch (e) {
      showProgress();
      setProgress({ status: "failed", msg: "提交失败：" + e.message, log: [] });
    } finally {
      state.submitting = false;
      $("go").classList.remove("loading");
      $("goText").textContent = "生成 PPT";
      updateActionRow();
    }
  }
  $("go").addEventListener("click", submit);
  $("retryBtn").addEventListener("click", submit);

  // ── 任务进度 ──
  function bindJob(id, fresh) {
    state.job = id;
    if (fresh) state.logSeen = 0;
    showProgress();
    startPoll();
  }
  function showProgress() { $("progress").style.display = ""; }
  function startPoll() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      if (!state.job) return;
      try {
        const r = await fetch("/api/jobs/" + state.job);
        if (!r.ok) throw new Error();
        setProgress(await r.json());
      } catch (e) { /* 单次失败忽略 */ }
    }, 2000);
  }
  function stopPoll() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  function setProgress(job) {
    const done = job.status === "done", failed = job.status === "failed";
    $("stRow").className = "st-row " + (job.status === "running" ? "running" : "");
    const stMap = { queued: "排队中…", running: "正在生成…" };
    $("stText").textContent = failed ? "生成失败"
      : done ? "生成完成" : (stMap[job.status] || "") + " " + (job.msg || "");
    // 百分比只来自后端真实页进度 (pages_done/pages_total), 无页数时不显示
    if (done) { $("stPct").textContent = "100%"; $("barFill").style.width = "100%"; }
    else if (job.pages_total > 0) {
      const pct = Math.round((job.pages_done / job.pages_total) * 100);
      $("stPct").textContent = pct + "%（" + job.pages_done + "/" + job.pages_total + " 页）";
      $("barFill").style.width = pct + "%";
    } else { $("stPct").textContent = ""; $("barFill").style.width = "0"; }

    const logEl = $("log");
    if (job.log && job.log.length > state.logSeen) {
      const frag = document.createDocumentFragment();
      for (const line of job.log.slice(state.logSeen)) {
        const div = document.createElement("div");
        div.textContent = line;
        if (/✓|完成|通过/.test(line)) div.className = "ok";
        else if (/✗|失败|缺页/.test(line)) div.className = "bad";
        frag.appendChild(div);
      }
      logEl.appendChild(frag);
      state.logSeen = job.log.length;
      logEl.scrollTop = logEl.scrollHeight;
    }
    $("dlRow").classList.toggle("show", done);
    $("errRow").classList.toggle("show", failed);
    if (done) {
      $("dlLink").href = "/api/jobs/" + job.id + "/download";
      $("dlNote").textContent = job.file_name +
        (job.template_name ? " · 模板: " + job.template_name : "");
    }
    if (failed) $("errMsg").textContent = job.error || job.msg || "未知错误";
    if (done || failed) { stopPoll(); refreshJobs(); markSel(job.id); }
  }

  // ── 历史任务侧栏 ──
  async function refreshJobs() {
    try {
      const r = await fetch("/api/jobs");
      const jobs = await r.json();
      const ul = $("jobs");
      ul.textContent = "";
      if (!jobs.length) {
        ul.innerHTML = '<li class="empty-side" style="cursor:default">暂无历史任务</li>';
        return;
      }
      const stZh = { queued: "排队中", running: "生成中", done: "已完成", failed: "失败" };
      for (const j of jobs.slice(0, 30)) {
        const li = document.createElement("li");
        li.setAttribute("role", "button");
        li.setAttribute("tabindex", "0");
        li.dataset.jobId = j.id;
        if (j.id === state.job) li.classList.add("sel");
        const r1 = document.createElement("div");
        r1.className = "r1";
        const nm = document.createElement("span");
        nm.className = "name"; nm.textContent = j.file_name; nm.title = j.file_name;
        const chip = document.createElement("span");
        chip.className = "chip " + j.status;
        chip.textContent = stZh[j.status] || j.status;
        r1.append(nm, chip);
        const tm = document.createElement("div");
        tm.className = "time";
        tm.textContent = (j.created || "").replace("T", " ") +
          (j.template_name ? " · 自定义模板" : "");
        li.append(r1, tm);
        li.addEventListener("click", () => {
          state.logSeen = 0;
          bindJob(j.id, false);
          fetch("/api/jobs/" + j.id).then((r) => r.json()).then(setProgress).catch(() => {});
          markSel(j.id);
          closeSide();
        });
        ul.appendChild(li);
      }
    } catch (e) { /* ignore */ }
  }
  function markSel(id) {
    document.querySelectorAll("#jobs li").forEach((li) =>
      li.classList.toggle("sel", li.dataset.jobId === id));
  }

  // ── 窄屏侧栏开合 ──
  function closeSide() {
    $("sidebar").classList.remove("open");
    $("sideMask").classList.remove("show");
  }
  $("sideToggle").addEventListener("click", () => {
    const open = $("sidebar").classList.toggle("open");
    $("sideMask").classList.toggle("show", open);
  });
  $("sideMask").addEventListener("click", closeSide);

  // ── 初始化 ──
  renderDocZone();
  refreshJobs();
})();
