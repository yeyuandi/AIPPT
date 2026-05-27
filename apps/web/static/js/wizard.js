/**
 * 向导前端：分步调用 API，轮询 progress.json；导航与执行按钮互锁。
 */
/** @type {string|null} */
let jobId = null;

/** 步骤 4：当前单页预览可用的 outline 页索引（0 起）；无对应 HTML 时为 null */
let slidePreviewActiveIndex = null;

/** 步骤 4：HTML 编辑弹窗打开的页索引（保存时用，避免切换列表后写错文件） */
let slideHtmlEditModalIndex = null;

/**
 * 步骤 2：单页大纲草稿（与磁盘 deck_outline.json 中每项字段对齐）。
 *
 * @typedef {{ title: string, summary: string, bullets: string[], html_file: string, pptx_file: string }} OutlineSlideDraft
 */

/** @type {OutlineSlideDraft[]|null} */
let outlineEditorSlides = null;

/** @type {number} */
let outlineEditorActiveIndex = 0;

/** 历史任务恢复请求序号（用于丢弃过期响应） */
let historyRestoreSeq = 0;

/** 是否已有异步任务在执行（轮询期间也算） */
let wizardBusy = false;

/** 各步「执行动作」是否已成功完成（决定「下一步」是否可点） */
const stepDone = {
  1: false,
  2: false,
  3: false,
  4: false,
  5: false,
  6: false,
};

/**
 * @param {string} msg - 提示文案
 * @param {'danger'|'success'|'info'} kind - Bootstrap alert 变体
 */
function showAlert(msg, kind = "danger") {
  const host = document.getElementById("alert-host");
  if (!host) return;
  host.innerHTML = `<div class="alert alert-${kind} alert-dismissible fade show" role="status">
    ${escapeHtml(msg)}
    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
  </div>`;
}

/** @type {ReturnType<typeof setTimeout>|null} */
let wizardTransientModalHideTimer = null;

/**
 * 居中模态框提示：`backdrop: static` 不可点击遮罩关闭；若干秒后自动关闭。
 *
 * @param {string} msg
 * @param {number} [ttlMs]
 */
function showTransientCenterModal(msg, ttlMs = 2600) {
  const modalEl = document.getElementById("wizard-transient-modal");
  const msgEl = document.getElementById("wizard-transient-modal-msg");
  if (!modalEl || !msgEl) return;
  msgEl.textContent = msg;
  const B = globalThis.bootstrap;
  if (!B?.Modal) {
    showAlert(msg, "success");
    return;
  }
  const inst = B.Modal.getOrCreateInstance(modalEl, { backdrop: "static", keyboard: false });
  inst.show();
  if (wizardTransientModalHideTimer !== null) {
    window.clearTimeout(wizardTransientModalHideTimer);
    wizardTransientModalHideTimer = null;
  }
  wizardTransientModalHideTimer = window.setTimeout(() => {
    wizardTransientModalHideTimer = null;
    inst.hide();
  }, ttlMs);
}

/**
 * 点击执行类按钮后立即提示「已提交」。
 *
 * @param {string} actionLabel - 简短动作名称
 */
function showSubmitNotice(actionLabel) {
  showAlert(`「${actionLabel}」请求已提交，正在执行请稍候…`, "info");
}

/**
 * @param {string} s - 原始字符串
 * @returns {string} 转义后文本节点安全内容
 */
function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/**
 * @param {boolean} busy - true 时禁止所有「上一步 / 下一步」
 */
function setWizardBusy(busy) {
  wizardBusy = busy;
  syncNavButtons();
}

/**
 * 设置执行按钮禁用态（成功后保持禁用；失败后在调用方恢复）。
 *
 * @param {HTMLButtonElement|null} btn - 按钮元素
 * @param {boolean} disabled - 是否禁用
 */
function setExecuteDisabled(btn, disabled) {
  if (!btn) return;
  btn.disabled = disabled;
}

/**
 * 根据 stepDone / wizardBusy 更新各面板内的上一步、下一步。
 */
function syncNavButtons() {
  document.querySelectorAll("[data-wizard-pane]").forEach((pane) => {
    const fromStep = Number(pane.getAttribute("data-wizard-pane"));
    if (!Number.isFinite(fromStep)) return;
    pane.querySelectorAll("[data-go-step]").forEach((btn) => {
      const target = Number(btn.getAttribute("data-go-step"));
      if (!Number.isFinite(target)) return;
      if (target > fromStep) {
        let allowForward = stepDone[fromStep];
        if (fromStep === 1 && target === 2) {
          const taVal = (document.getElementById("document-text")?.value || "").trim();
          const hasFileDraft = Boolean(fileInputStep1?.files?.length);
          const step1MinCharsNoFile = 5;
          allowForward =
            stepDone[1] || hasFileDraft || taVal.length >= step1MinCharsNoFile;
        }
        btn.disabled = !allowForward || wizardBusy;
      } else if (target < fromStep) {
        btn.disabled = wizardBusy;
      }
    });
  });
}

/**
 * @param {Response} r - fetch 响应
 * @param {string} fallbackMsg - 解析失败时的提示前缀
 * @returns {Promise<Record<string, unknown>>}
 */
async function parseApiJson(r, fallbackMsg) {
  const text = await r.text();
  try {
    return JSON.parse(text);
  } catch {
    const low = text.trimStart().slice(0, 40).toLowerCase();
    if (low.startsWith("<!doctype") || low.startsWith("<html")) {
      throw new Error(
        "服务器返回了网页而非 JSON（多为接口 500 或未捕获异常）。请查看运行 Flask 的终端日志。"
      );
    }
    throw new Error(`${fallbackMsg}（HTTP ${r.status}）`);
  }
}

/**
 * 根据服务端 deck-template-ready 接口判断是否已生成 deck 模板，切换占位文案与 iframe。
 *
 * @returns {Promise<void>}
 */
/** deck_template 预览注入样式节点 id（与磁盘模板内 style 区分） */
const DECK_TEMPLATE_PREVIEW_SCROLL_STYLE_ID = "aippt-wizard-deck-template-preview-scroll";

/**
 * deck_template.html 为截图导出使用 overflow:hidden 并隐藏滚动条；向导内嵌预览需在固定高度 iframe 内纵向滚动。
 *
 * @param {HTMLIFrameElement|null} iframe - 步骤 3 主预览或全屏层 iframe
 */
function applyDeckTemplatePreviewScrollOverrides(iframe) {
  if (!iframe) return;
  try {
    const doc = iframe.contentDocument;
    if (!doc?.head) return;
    let el = doc.getElementById(DECK_TEMPLATE_PREVIEW_SCROLL_STYLE_ID);
    if (!el) {
      el = doc.createElement("style");
      el.id = DECK_TEMPLATE_PREVIEW_SCROLL_STYLE_ID;
      doc.head.appendChild(el);
    }
    el.textContent = `
      html {
        height: 100% !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
      }
      body {
        height: auto !important;
        min-height: 100% !important;
        overflow: visible !important;
      }
      .slide {
        height: auto !important;
        min-height: 100% !important;
        overflow: visible !important;
        scrollbar-width: auto !important;
        -ms-overflow-style: auto !important;
      }
      .slide::-webkit-scrollbar {
        display: revert !important;
      }
      .slide-body,
      .mid-grid,
      .toc-panel,
      .content-panel,
      .toc-list {
        overflow: visible !important;
        min-height: unset !important;
      }
      .slide-body,
      .mid-grid {
        flex: 0 0 auto !important;
      }
    `;
  } catch {
    /* sandbox 限制或跨域时无法写入 */
  }
}

/**
 * 绑定 load：每次载入 deck-template 后重新注入（模板文件可能更新）。
 *
 * @param {HTMLIFrameElement|null} iframe
 */
function bindDeckTemplatePreviewIframeScroll(iframe) {
  if (!iframe || iframe.dataset.aipptDeckTplScrollBound === "1") return;
  iframe.dataset.aipptDeckTplScrollBound = "1";
  iframe.addEventListener("load", () => applyDeckTemplatePreviewScrollOverrides(iframe));
}

async function refreshTemplatePreviewPane() {
  const iframe = document.getElementById("iframe-template");
  const ph = document.getElementById("template-preview-placeholder");
  if (!iframe || !ph) return;
  const emptyText = "暂时没有预览的内容";
  try {
    if (!jobId) {
      ph.textContent = emptyText;
      ph.classList.remove("d-none");
      iframe.classList.add("d-none");
      iframe.removeAttribute("src");
      return;
    }
    try {
      const r = await fetch(`/api/jobs/${jobId}/deck-template-ready`);
      if (!r.ok) {
        ph.textContent = emptyText;
        ph.classList.remove("d-none");
        iframe.classList.add("d-none");
        iframe.removeAttribute("src");
        return;
      }
      const data = await r.json();
      if (data && data.ready) {
        ph.classList.add("d-none");
        iframe.classList.remove("d-none");
        iframe.src = `/api/jobs/${jobId}/html/deck-template`;
      } else {
        ph.textContent = emptyText;
        ph.classList.remove("d-none");
        iframe.classList.add("d-none");
        iframe.removeAttribute("src");
      }
    } catch {
      ph.textContent = emptyText;
      ph.classList.remove("d-none");
      iframe.classList.add("d-none");
      iframe.removeAttribute("src");
    }
  } finally {
    syncTemplateFullscreenIframeFromMain();
    syncTemplatePreviewFullscreenToolbar();
  }
}

/**
 * @param {number} step - 1～6
 */
function setActiveStep(step) {
  document.querySelectorAll("[data-step-indicator]").forEach((el) => {
    const n = Number(el.getAttribute("data-step-indicator"));
    el.classList.toggle("active", n === step);
    el.classList.toggle("done", n < step);
  });
  document.querySelectorAll("[data-wizard-pane]").forEach((pane) => {
    pane.hidden = Number(pane.getAttribute("data-wizard-pane")) !== step;
  });
  if (step === 3 && jobId) {
    void refreshTemplatePreviewPane().catch(() => {});
  }
  if (step === 4 && jobId) {
    void refreshSlidePickerFromServer().catch((err) => showAlert(err.message));
  }
  if (step === 2 && jobId) {
    void ensureOutlineEditorHydrated().catch(() => {});
  }
  syncNavButtons();
}

/**
 * 步骤 4：「编辑」仅在当前页已有可预览的 slide HTML 时可点。
 */
function syncSlideHtmlEditButton() {
  const btn = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-slide-html-edit"));
  if (!btn) return;
  btn.disabled = slidePreviewActiveIndex === null || !jobId;
}

/**
 * 从服务端 deck_outline.json 填充页面列表并绑定单页预览 iframe（无对应 HTML 文件时显示占位）。
 *
 * @returns {Promise<void>}
 */
async function refreshSlidePickerFromServer() {
  const listEl = document.getElementById("slide-picker-list");
  const iframe = document.getElementById("iframe-slide");
  const ph = document.getElementById("slide-preview-placeholder");
  if (!jobId || !listEl || !iframe || !ph) return;

  slidePreviewActiveIndex = null;
  syncSlideHtmlEditButton();

  /** @param {string} [message] */
  const showSlidePreviewEmpty = (message = "暂无相关页面") => {
    slidePreviewActiveIndex = null;
    syncSlideHtmlEditButton();
    ph.textContent = message;
    ph.classList.remove("d-none");
    iframe.classList.add("d-none");
    iframe.removeAttribute("src");
  };

  const r = await fetch(`/api/jobs/${jobId}/outline-json`);
  const data = await parseApiJson(r, "大纲 JSON 加载失败");
  if (!r.ok) throw new Error(String(data.error || "无法加载 deck_outline.json"));

  const slides = Array.isArray(data.slides) ? data.slides : [];
  listEl.innerHTML = "";

  /** @param {number} idx */
  const selectSlide = async (idx) => {
    listEl.querySelectorAll(".slide-picker-item").forEach((btn) => {
      const el = /** @type {HTMLButtonElement} */ (btn);
      const j = Number(el.dataset.slideIndex);
      const on = j === idx;
      el.classList.toggle("active", on);
      el.setAttribute("aria-selected", on ? "true" : "false");
    });

    const headR = await fetch(`/api/jobs/${jobId}/html/slide/${idx}`, { method: "HEAD" });
    if (!headR.ok) {
      showSlidePreviewEmpty();
      return;
    }
    slidePreviewActiveIndex = idx;
    syncSlideHtmlEditButton();
    ph.classList.add("d-none");
    iframe.classList.remove("d-none");
    iframe.src = `/api/jobs/${jobId}/html/slide/${idx}`;
  };

  slides.forEach((slide, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "slide-picker-item";
    btn.setAttribute("role", "option");
    btn.dataset.slideIndex = String(i);
    const title = typeof slide.title === "string" ? slide.title : "未命名";
    btn.textContent = `${i}. ${title}`;
    btn.addEventListener("click", () => {
      void selectSlide(i);
    });
    listEl.appendChild(btn);
  });

  if (!slides.length) {
    showSlidePreviewEmpty();
    return;
  }

  await selectSlide(0);
}

/**
 * @returns {Promise<Record<string, unknown>>}
 */
async function fetchProgress() {
  const r = await fetch(`/api/jobs/${jobId}/progress`);
  const data = await parseApiJson(r, "进度接口解析失败");
  if (!r.ok) throw new Error(String(data.error || `读取进度失败 HTTP ${r.status}`));
  return data;
}

/**
 * @param {(p: Record<string, unknown>) => boolean} donePred - 结束条件
 * @param {(p: Record<string, unknown>) => void} [onTick] - 每次轮询回调
 */
async function pollUntil(donePred, onTick) {
  for (;;) {
    const p = await fetchProgress();
    if (typeof onTick === "function") onTick(p);
    if (p.phase === "error") throw new Error(String(p.message || "未知错误"));
    if (donePred(p)) return p;
    await new Promise((res) => setTimeout(res, 900));
  }
}

function setProgressBar(frac, labelEl, barEl, text) {
  const pct = Math.round(Math.min(1, Math.max(0, frac)) * 100);
  if (labelEl) labelEl.textContent = text;
  if (barEl) {
    barEl.style.width = `${pct}%`;
    barEl.setAttribute("aria-valuenow", String(pct));
  }
}

/**
 * @param {XMLHttpRequest} xhr
 * @returns {Record<string, unknown>}
 */
function parseXhrResponseJson(xhr) {
  const text = xhr.responseText || "";
  try {
    return JSON.parse(text);
  } catch {
    const low = text.trimStart().slice(0, 40).toLowerCase();
    if (low.startsWith("<!doctype") || low.startsWith("<html")) {
      throw new Error("服务器返回了网页而非 JSON（请查看 Flask 终端日志）。");
    }
    throw new Error(`接口解析失败（HTTP ${xhr.status}）`);
  }
}

/**
 * 步骤 1：multipart 创建任务，支持 upload.progress 进度回调。
 *
 * @param {FormData} fd - 表单数据
 * @param {(loaded: number, total: number) => void} onUploadProgress - total 为 0 表示未知总长
 * @returns {Promise<Record<string, unknown>>}
 */
function postJobMultipart(fd, onUploadProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.responseType = "text";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onUploadProgress(e.loaded, e.total);
      else onUploadProgress(e.loaded, 0);
    };
    xhr.onload = () => {
      try {
        const data = parseXhrResponseJson(xhr);
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(String(data.error || `HTTP ${xhr.status}`)));
      } catch (err) {
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    };
    xhr.onerror = () => reject(new Error("网络错误，请检查连接"));
    xhr.send(fd);
  });
}

const fileInputStep1 = /** @type {HTMLInputElement|null} */ (document.getElementById("file"));
const uploadFileStatusEl = document.getElementById("upload-file-status");

/** @type {ReturnType<typeof bootstrap.Modal["getOrCreateInstance"]>|null} */
let uploadModalCached = null;

/** @type {ReturnType<typeof setTimeout>|null} */
let uploadModalSuccessCloseTimer = null;

/**
 * @returns {ReturnType<typeof bootstrap.Modal["getOrCreateInstance"]>|null}
 */
function getUploadModalInstance() {
  const el = document.getElementById("upload-run-modal");
  const B = globalThis.bootstrap;
  if (!el || !B?.Modal) return null;
  if (!uploadModalCached) {
    uploadModalCached = B.Modal.getOrCreateInstance(el, { backdrop: "static", keyboard: false });
  }
  return uploadModalCached;
}

function clearUploadModalSuccessTimer() {
  if (uploadModalSuccessCloseTimer != null) {
    window.clearTimeout(uploadModalSuccessCloseTimer);
    uploadModalSuccessCloseTimer = null;
  }
}

/**
 * 恢复加载弹窗初始布局（关闭后或下一次打开前）。
 */
function resetUploadModalPhases() {
  clearUploadModalSuccessTimer();
  document.getElementById("upload-modal-phase-loading")?.classList.remove("d-none");
  document.getElementById("upload-modal-phase-success")?.classList.add("d-none");
  document.getElementById("upload-modal-phase-error")?.classList.add("d-none");
  const bar = /** @type {HTMLElement|null} */ (document.getElementById("upload-modal-progress-bar"));
  const lbl = document.getElementById("upload-modal-progress-label");
  const statusLine = document.getElementById("upload-modal-status-line");
  if (bar) {
    bar.className = "progress-bar bg-primary";
    bar.style.width = "0%";
    bar.removeAttribute("aria-valuenow");
  }
  if (lbl) lbl.textContent = "";
  if (statusLine) statusLine.textContent = "正在处理，请稍候…";
}

/**
 * @param {boolean} hasFile - 是否包含附件（决定是否显示上传百分比）
 */
function showUploadModalLoadingState(hasFile) {
  resetUploadModalPhases();
  const statusLine = document.getElementById("upload-modal-status-line");
  const bar = /** @type {HTMLElement|null} */ (document.getElementById("upload-modal-progress-bar"));
  if (statusLine) statusLine.textContent = hasFile ? "正在上传并解析文档…" : "正在提交正文…";
  if (bar) {
    if (!hasFile) {
      bar.classList.add("progress-bar-striped", "progress-bar-animated");
      bar.style.width = "100%";
    } else {
      bar.style.width = "0%";
    }
  }
  getUploadModalInstance()?.show();
}

/**
 * 成功后短暂提示并自动关闭弹窗。
 */
function showUploadModalSuccessAndAutoClose() {
  document.getElementById("upload-modal-phase-loading")?.classList.add("d-none");
  document.getElementById("upload-modal-phase-success")?.classList.remove("d-none");
  clearUploadModalSuccessTimer();
  uploadModalSuccessCloseTimer = window.setTimeout(() => {
    uploadModalSuccessCloseTimer = null;
    getUploadModalInstance()?.hide();
  }, 720);
}

/**
 * @param {string} message - 错误文案
 */
function showUploadModalError(message) {
  document.getElementById("upload-modal-phase-loading")?.classList.add("d-none");
  const errWrap = document.getElementById("upload-modal-phase-error");
  const msgEl = document.getElementById("upload-modal-error-msg");
  errWrap?.classList.remove("d-none");
  if (msgEl) msgEl.textContent = message;
}

document.getElementById("upload-run-modal")?.addEventListener("hidden.bs.modal", () => {
  resetUploadModalPhases();
});

document.getElementById("upload-modal-btn-dismiss")?.addEventListener("click", () => {
  getUploadModalInstance()?.hide();
});

const btnUpload = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-upload-submit"));

document.getElementById("btn-pick-file")?.addEventListener("click", () => fileInputStep1?.click());

fileInputStep1?.addEventListener("change", () => {
  const f = fileInputStep1.files?.[0];
  if (uploadFileStatusEl) uploadFileStatusEl.textContent = f ? `已附加：${f.name}` : "未附加文件";
  syncNavButtons();
});

/**
 * 步骤 1：输入框内容与下方正文预览同步（输入与失焦时触发）。
 */
function syncStep1DocPreviewFromTextarea() {
  const ta = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("document-text"));
  const pre = document.getElementById("doc-preview");
  if (!ta || !pre) return;
  pre.textContent = ta.value;
}

document.getElementById("document-text")?.addEventListener("input", () => {
  syncStep1DocPreviewFromTextarea();
  syncNavButtons();
});
document.getElementById("document-text")?.addEventListener("blur", () => {
  syncStep1DocPreviewFromTextarea();
  syncNavButtons();
});

/**
 * 步骤 1：提交正文/附件创建任务（与「加载」按钮逻辑一致）。
 *
 * @returns {Promise<boolean>} 是否成功（可用于下一步跳转）
 */
async function executeStep1Load() {
  const textArea = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("document-text"));
  const bodyText = (textArea?.value || "").trim();
  const hasFile = Boolean(fileInputStep1?.files?.length);
  const minCharsNoFile = 5;
  if (!bodyText && !hasFile) {
    showAlert("请上传文稿文件或在输入框中填写正文");
    return false;
  }
  if (!hasFile && bodyText.length < minCharsNoFile) {
    showAlert(`未上传文件时，正文至少输入 ${minCharsNoFile} 个字`);
    return false;
  }

  const llmSel = /** @type {HTMLSelectElement|null} */ (document.getElementById("llm-provider"));
  const fd = new FormData();
  fd.append("document_text", textArea?.value ?? "");
  if (hasFile && fileInputStep1?.files?.[0]) fd.append("file", fileInputStep1.files[0]);
  fd.append("llm_provider", llmSel?.value ?? "");

  const modalBar = /** @type {HTMLElement|null} */ (document.getElementById("upload-modal-progress-bar"));
  const modalLbl = document.getElementById("upload-modal-progress-label");

  showUploadModalLoadingState(hasFile);
  setWizardBusy(true);
  setExecuteDisabled(btnUpload, true);

  try {
    const data = await postJobMultipart(fd, (loaded, total) => {
      if (total > 0 && modalBar && modalLbl) {
        modalBar.classList.remove("progress-bar-striped", "progress-bar-animated");
        const frac = loaded / total;
        setProgressBar(frac, modalLbl, modalBar, `正在上传… ${Math.round(frac * 100)}%`);
      }
    });
    if (!data.job_id) throw new Error(String(data.error || "加载失败"));
    jobId = /** @type {string} */ (data.job_id);
    const histSel = /** @type {HTMLSelectElement|null} */ (document.getElementById("history-job-select"));
    if (histSel) histSel.value = "";
    stepDone[2] = false;
    stepDone[3] = false;
    stepDone[4] = false;
    stepDone[5] = false;
    stepDone[6] = false;
    outlineEditorSlides = null;
    outlineEditorActiveIndex = 0;
    resetOutlineEditorToEmpty();
    const omClear = document.getElementById("outline-meta");
    if (omClear) omClear.textContent = "";
    const summary =
      typeof data.source_summary === "string" && data.source_summary
        ? `${data.source_summary} · `
        : "";
    document.getElementById("upload-meta").textContent =
      `${summary}任务 ${jobId} · 约 ${data.char_count} 字符${data.truncated ? "（预览已截断）" : ""}`;
    const previewEl = document.getElementById("doc-preview");
    if (previewEl) {
      if (hasFile) {
        previewEl.textContent = String(data.preview ?? "");
      } else {
        previewEl.textContent = textArea?.value ?? String(data.preview ?? "");
      }
    }
    stepDone[1] = true;
    showUploadModalSuccessAndAutoClose();
    syncNavButtons();
    setExecuteDisabled(btnUpload, false);
    setWizardBusy(false);
    return true;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    showUploadModalError(msg);
    setExecuteDisabled(btnUpload, false);
    setWizardBusy(false);
    return false;
  }
}

document.getElementById("form-upload")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await executeStep1Load();
});

const btnOutline = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-outline"));

/** 大纲推理进行中（防重复提交） */
let outlineInferenceBusy = false;

/** 大纲弹窗示意进度条定时器 */
let outlineModalFakeProgressTimer = /** @type {ReturnType<typeof setInterval>|null} */ (null);

/** 终止本次大纲 POST 的 AbortController（「暂停推理」） */
let outlineInferenceAbortController = /** @type {AbortController|null} */ (null);

/** @type {ReturnType<typeof bootstrap.Modal["getOrCreateInstance"]>|null} */
let outlineModalInstance = null;

/**
 * 清除大纲弹窗示意进度动画。
 */
function clearOutlineModalFakeProgress() {
  if (outlineModalFakeProgressTimer !== null) {
    clearInterval(outlineModalFakeProgressTimer);
    outlineModalFakeProgressTimer = null;
  }
}

/**
 * 推理进行中：进度条从 0% 爬升至约 92%，结束后由 finishOutlineModalFakeProgress 收口。
 */
function startOutlineModalFakeProgress() {
  clearOutlineModalFakeProgress();
  const bar = document.getElementById("outline-modal-progress-bar");
  if (!bar) return;
  bar.style.width = "0%";
  bar.setAttribute("aria-valuenow", "0");
  bar.classList.add("progress-bar-striped", "progress-bar-animated");
  let w = 0;
  outlineModalFakeProgressTimer = setInterval(() => {
    if (w >= 92) return;
    w += Math.random() * 4 + 0.8;
    if (w > 92) w = 92;
    bar.style.width = `${w}%`;
    bar.setAttribute("aria-valuenow", String(Math.round(w)));
  }, 380);
}

/**
 * 推理结束：进度拉满并去掉条纹动画。
 */
function finishOutlineModalFakeProgress() {
  clearOutlineModalFakeProgress();
  const bar = document.getElementById("outline-modal-progress-bar");
  if (!bar) return;
  bar.style.width = "100%";
  bar.setAttribute("aria-valuenow", "100");
  bar.classList.remove("progress-bar-striped", "progress-bar-animated");
}

/**
 * Bootstrap 大纲弹窗实例（静态遮罩、禁止 Esc）。
 *
 * @returns {ReturnType<typeof bootstrap.Modal["getOrCreateInstance"]>|null}
 */
function getOutlineModalInstance() {
  const el = document.getElementById("outline-run-modal");
  const B = globalThis.bootstrap;
  if (!el || !B?.Modal) return null;
  if (!outlineModalInstance) {
    outlineModalInstance = B.Modal.getOrCreateInstance(el, { backdrop: "static", keyboard: false });
  }
  return outlineModalInstance;
}

/**
 * @param {unknown} raw - ``deck_outline.json`` 中 slides 数组的单项
 * @returns {OutlineSlideDraft}
 */
function normalizeOutlineSlide(raw) {
  const o = raw && typeof raw === "object" ? /** @type {Record<string, unknown>} */ (raw) : {};
  const title = typeof o.title === "string" ? o.title : "";
  const summary = typeof o.summary === "string" ? o.summary : "";
  const bullets = Array.isArray(o.bullets) ? o.bullets.map((b) => String(b ?? "")) : [];
  const html_file = typeof o.html_file === "string" ? o.html_file : "";
  const pptx_file = typeof o.pptx_file === "string" ? o.pptx_file : "";
  return { title, summary, bullets, html_file, pptx_file };
}

/**
 * 切换左侧列表 / 右侧表单占位与「暂无大纲」提示。
 */
function syncOutlineEditorChromeVisibility() {
  const hint = document.getElementById("outline-editor-list-hint");
  const heading = document.getElementById("outline-editor-heading");
  const list = document.getElementById("outline-editor-list");
  const placeholder = document.getElementById("outline-editor-form-placeholder");
  const wrap = document.getElementById("outline-editor-form-wrap");
  const has = Boolean(outlineEditorSlides && outlineEditorSlides.length > 0);
  if (hint) hint.classList.toggle("d-none", has);
  if (heading) heading.classList.toggle("d-none", !has);
  if (list) list.classList.toggle("d-none", !has);
  if (!has) {
    placeholder?.classList.remove("d-none");
    wrap?.classList.add("d-none");
  } else {
    placeholder?.classList.add("d-none");
    wrap?.classList.remove("d-none");
  }
}

/**
 * 清空步骤 2 大纲编辑器（如新任务或无大纲）。
 */
function resetOutlineEditorToEmpty() {
  outlineEditorSlides = null;
  outlineEditorActiveIndex = 0;
  const list = document.getElementById("outline-editor-list");
  if (list) list.innerHTML = "";
  const host = document.getElementById("outline-bullets-host");
  if (host) host.innerHTML = "";
  const titleEl = /** @type {HTMLInputElement|null} */ (document.getElementById("outline-slide-title"));
  const sumEl = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("outline-slide-summary"));
  if (titleEl) titleEl.value = "";
  if (sumEl) sumEl.value = "";
  syncOutlineEditorChromeVisibility();
}

/**
 * 用服务端根对象填充大纲编辑器。
 *
 * @param {Record<string, unknown>} root - ``DeckOutline`` JSON
 */
function hydrateOutlineEditorFromRoot(root) {
  const slidesRaw =
    root && typeof root === "object" && Array.isArray(root.slides) ? root.slides : [];
  outlineEditorSlides = slidesRaw.map((s) => normalizeOutlineSlide(s));
  outlineEditorActiveIndex = 0;
  syncOutlineEditorChromeVisibility();
  renderOutlineEditorList();
  if (outlineEditorSlides.length > 0) {
    renderOutlineEditorForm();
  } else {
    const host = document.getElementById("outline-bullets-host");
    if (host) host.innerHTML = "";
    const titleEl = /** @type {HTMLInputElement|null} */ (document.getElementById("outline-slide-title"));
    const sumEl = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("outline-slide-summary"));
    if (titleEl) titleEl.value = "";
    if (sumEl) sumEl.value = "";
  }
}

/**
 * 将右侧表单写回当前索引对应的草稿项。
 */
function commitOutlineFormIntoActiveSlide() {
  if (!outlineEditorSlides || outlineEditorSlides.length === 0) return;
  if (outlineEditorActiveIndex < 0 || outlineEditorActiveIndex >= outlineEditorSlides.length) return;
  const slide = outlineEditorSlides[outlineEditorActiveIndex];
  const titleEl = /** @type {HTMLInputElement|null} */ (document.getElementById("outline-slide-title"));
  const sumEl = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("outline-slide-summary"));
  if (titleEl) slide.title = titleEl.value;
  if (sumEl) slide.summary = sumEl.value;
  const host = document.getElementById("outline-bullets-host");
  if (host) {
    slide.bullets = Array.from(host.querySelectorAll("[data-outline-bullet-input]")).map(
      (el) => /** @type {HTMLInputElement} */ (el).value,
    );
  }
}

/**
 * 校验保存前每页标题与概要是否非空。
 *
 * @param {OutlineSlideDraft[]} slides
 * @returns {string[]} 人类可读的问题说明（逐页）
 */
function validateOutlineSlidesForSave(slides) {
  /** @type {string[]} */
  const issues = [];
  slides.forEach((s, i) => {
    const page = i + 1;
    const hasTitle = Boolean(String(s.title ?? "").trim());
    const hasSummary = Boolean(String(s.summary ?? "").trim());
    if (!hasTitle && !hasSummary) issues.push(`第 ${page} 页：标题与概要均未填写`);
    else if (!hasTitle) issues.push(`第 ${page} 页：标题未填写`);
    else if (!hasSummary) issues.push(`第 ${page} 页：概要未填写`);
  });
  return issues;
}

/**
 * 弹出校验失败说明（Bootstrap Modal）。
 *
 * @param {string[]} issues
 */
function showOutlineValidationModal(issues) {
  const ul = document.getElementById("outline-validation-modal-list");
  const modalEl = document.getElementById("outline-validation-modal");
  if (!ul || !modalEl) {
    showAlert(issues.length ? issues.join("；") : "校验失败");
    return;
  }
  ul.innerHTML = "";
  issues.forEach((t) => {
    const li = document.createElement("li");
    li.className = "mb-1";
    li.textContent = t;
    ul.appendChild(li);
  });
  const B = globalThis.bootstrap;
  if (!B?.Modal) {
    showAlert(issues.join("\n"));
    return;
  }
  B.Modal.getOrCreateInstance(modalEl).show();
}

/**
 * @param {string} iconBiClass - Bootstrap Icons 文件名段（如 plus-lg）
 * @param {string} label - 提示与 aria-label
 * @param {() => void} onClick
 * @param {boolean} [disabled]
 */
function createOutlineRowIconButton(iconBiClass, label, onClick, disabled = false) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "btn btn-sm btn-wiz-outline outline-editor-icon-btn";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.disabled = disabled;
  b.innerHTML = `<i class="bi bi-${iconBiClass}" aria-hidden="true"></i>`;
  b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    if (!b.disabled) onClick();
  });
  return b;
}

/**
 * 在本条之后插入空白页并选中。
 *
 * @param {number} index - 当前页索引（0 起）
 */
function outlineInsertAfter(index) {
  if (!outlineEditorSlides) return;
  commitOutlineFormIntoActiveSlide();
  const blank = normalizeOutlineSlide({});
  outlineEditorSlides.splice(index + 1, 0, blank);
  outlineEditorActiveIndex = index + 1;
  renderOutlineEditorList();
  renderOutlineEditorForm();
}

/**
 * 删除指定页（至少保留一页）。
 *
 * @param {number} index
 */
function outlineDeleteAt(index) {
  if (!outlineEditorSlides || index < 0 || index >= outlineEditorSlides.length) return;
  if (outlineEditorSlides.length <= 1) {
    showAlert("至少保留一页大纲。");
    return;
  }
  commitOutlineFormIntoActiveSlide();
  outlineEditorSlides.splice(index, 1);
  if (outlineEditorActiveIndex > index) outlineEditorActiveIndex -= 1;
  else if (outlineEditorActiveIndex === index)
    outlineEditorActiveIndex = Math.min(index, outlineEditorSlides.length - 1);
  renderOutlineEditorList();
  renderOutlineEditorForm();
}

/**
 * @param {number} index
 */
function outlineMoveUp(index) {
  if (!outlineEditorSlides || index <= 0) return;
  commitOutlineFormIntoActiveSlide();
  const arr = outlineEditorSlides;
  const t = arr[index - 1];
  arr[index - 1] = arr[index];
  arr[index] = t;
  if (outlineEditorActiveIndex === index) outlineEditorActiveIndex = index - 1;
  else if (outlineEditorActiveIndex === index - 1) outlineEditorActiveIndex = index;
  renderOutlineEditorList();
  renderOutlineEditorForm();
}

/**
 * @param {number} index
 */
function outlineMoveDown(index) {
  if (!outlineEditorSlides || index < 0 || index >= outlineEditorSlides.length - 1) return;
  commitOutlineFormIntoActiveSlide();
  const arr = outlineEditorSlides;
  const t = arr[index + 1];
  arr[index + 1] = arr[index];
  arr[index] = t;
  if (outlineEditorActiveIndex === index) outlineEditorActiveIndex = index + 1;
  else if (outlineEditorActiveIndex === index + 1) outlineEditorActiveIndex = index;
  renderOutlineEditorList();
  renderOutlineEditorForm();
}

/**
 * 渲染左侧大纲页列表（可选中 + 插入 / 删除 / 上移 / 下移）。
 */
function renderOutlineEditorList() {
  const list = document.getElementById("outline-editor-list");
  if (!list || !outlineEditorSlides) return;
  list.innerHTML = "";
  const n = outlineEditorSlides.length;
  outlineEditorSlides.forEach((slide, i) => {
    const row = document.createElement("div");
    row.className = "outline-editor-row";
    row.classList.toggle("active", i === outlineEditorActiveIndex);
    row.dataset.outlineIndex = String(i);
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", `第 ${i + 1} 页`);

    const mainBtn = document.createElement("button");
    mainBtn.type = "button";
    mainBtn.className = "outline-editor-item-main";
    mainBtn.setAttribute("role", "option");
    mainBtn.dataset.outlineIndex = String(i);
    mainBtn.setAttribute("aria-selected", i === outlineEditorActiveIndex ? "true" : "false");

    const num = document.createElement("span");
    num.className = "outline-editor-item-num";
    num.textContent = `${i + 1}.`;

    const text = document.createElement("span");
    text.className = "outline-editor-item-text";
    const label = slide.title.trim() || "未命名";
    text.textContent = label;
    text.title = label;

    mainBtn.append(num, text);
    mainBtn.addEventListener("click", () => selectOutlineEditorSlide(i));

    const actions = document.createElement("div");
    actions.className = "outline-editor-row-actions";

    actions.appendChild(
      createOutlineRowIconButton("plus-lg", "在本页后插入", () => outlineInsertAfter(i)),
    );
    actions.appendChild(
      createOutlineRowIconButton("trash", "删除本页", () => outlineDeleteAt(i), n <= 1),
    );
    actions.appendChild(
      createOutlineRowIconButton("arrow-up", "上移", () => outlineMoveUp(i), i === 0),
    );
    actions.appendChild(
      createOutlineRowIconButton("arrow-down", "下移", () => outlineMoveDown(i), i >= n - 1),
    );

    row.append(mainBtn, actions);
    list.appendChild(row);
  });
}

/**
 * @param {number} idx - outline 页索引
 */
function selectOutlineEditorSlide(idx) {
  if (!outlineEditorSlides || idx < 0 || idx >= outlineEditorSlides.length) return;
  commitOutlineFormIntoActiveSlide();
  outlineEditorActiveIndex = idx;
  renderOutlineEditorList();
  renderOutlineEditorForm();
}

/**
 * @param {OutlineSlideDraft} slide - 当前页草稿
 */
function renderOutlineBulletsHost(slide) {
  const host = document.getElementById("outline-bullets-host");
  if (!host) return;
  host.innerHTML = "";
  const nb = slide.bullets.length;
  slide.bullets.forEach((text, bi) => {
    const row = document.createElement("div");
    row.className = "d-flex flex-nowrap gap-2 mb-2 align-items-center outline-bullet-row w-100";

    const inp = document.createElement("input");
    inp.type = "text";
    inp.className = "form-control flex-grow-1 min-w-0";
    inp.value = text;
    inp.dataset.outlineBulletInput = "1";
    inp.setAttribute("aria-label", `要点 ${bi + 1}`);

    const actions = document.createElement("div");
    actions.className = "outline-editor-row-actions flex-shrink-0";

    actions.appendChild(
      createOutlineRowIconButton("plus-lg", "在本条后插入要点", () => {
        commitOutlineFormIntoActiveSlide();
        const cur = outlineEditorSlides?.[outlineEditorActiveIndex];
        if (!cur) return;
        cur.bullets.splice(bi + 1, 0, "");
        renderOutlineEditorForm();
      }),
    );
    actions.appendChild(
      createOutlineRowIconButton("trash", "删除本条要点", () => {
        commitOutlineFormIntoActiveSlide();
        const cur = outlineEditorSlides?.[outlineEditorActiveIndex];
        if (!cur) return;
        cur.bullets.splice(bi, 1);
        renderOutlineEditorForm();
      }),
    );
    actions.appendChild(
      createOutlineRowIconButton("arrow-up", "上移", () => {
        commitOutlineFormIntoActiveSlide();
        const cur = outlineEditorSlides?.[outlineEditorActiveIndex];
        if (!cur || bi <= 0) return;
        const arr = cur.bullets;
        const t = arr[bi - 1];
        arr[bi - 1] = arr[bi];
        arr[bi] = t;
        renderOutlineEditorForm();
      }, bi === 0),
    );
    actions.appendChild(
      createOutlineRowIconButton("arrow-down", "下移", () => {
        commitOutlineFormIntoActiveSlide();
        const cur = outlineEditorSlides?.[outlineEditorActiveIndex];
        if (!cur || bi >= cur.bullets.length - 1) return;
        const arr = cur.bullets;
        const t = arr[bi + 1];
        arr[bi + 1] = arr[bi];
        arr[bi] = t;
        renderOutlineEditorForm();
      }, bi >= nb - 1),
    );

    row.append(inp, actions);
    host.appendChild(row);
  });
}

/**
 * 根据 ``outlineEditorActiveIndex`` 刷新右侧表单。
 */
function renderOutlineEditorForm() {
  if (!outlineEditorSlides || outlineEditorSlides.length === 0) return;
  const ai = Math.min(Math.max(0, outlineEditorActiveIndex), outlineEditorSlides.length - 1);
  outlineEditorActiveIndex = ai;
  const slide = outlineEditorSlides[ai];
  if (!slide) return;
  const titleEl = /** @type {HTMLInputElement|null} */ (document.getElementById("outline-slide-title"));
  const sumEl = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("outline-slide-summary"));
  if (titleEl) titleEl.value = slide.title;
  if (sumEl) sumEl.value = slide.summary;
  renderOutlineBulletsHost(slide);
}

/**
 * 进入步骤 2 且内存中尚无草稿时，尝试从磁盘加载 ``deck_outline.json``。
 *
 * @returns {Promise<void>}
 */
async function ensureOutlineEditorHydrated() {
  if (!jobId || outlineEditorSlides !== null) return;
  try {
    const r = await fetch(`/api/jobs/${jobId}/outline-json`);
    if (!r.ok) return;
    const root = await parseApiJson(r, "outline-json 加载失败");
    if (typeof root !== "object" || root === null) return;
    hydrateOutlineEditorFromRoot(/** @type {Record<string, unknown>} */ (root));
  } catch {
    /* 404 或无文件：保持占位 */
  }
}

/**
 * 将大纲接口返回写入步骤 2 编辑器。
 *
 * @param {Record<string, unknown>} data - `/outline` JSON
 */
function applyOutlineResponseToStep(data) {
  const oj = data.outline_json;
  if (oj != null && typeof oj === "object") {
    hydrateOutlineEditorFromRoot(/** @type {Record<string, unknown>} */ (oj));
  } else {
    resetOutlineEditorToEmpty();
  }
  const meta = document.getElementById("outline-meta");
  const slideCount = data.slide_count;
  if (meta && typeof slideCount === "number") {
    meta.textContent = `共 ${slideCount} 页 · 已写入任务目录 deck_outline.json / deck_outline.txt`;
  }
}

/**
 * 根据历史任务 hints 设置各步「已完成」标记。
 *
 * @param {Record<string, unknown>} hints - 服务端 wizard-restore 中的 hints
 */
function applyStepDoneFromRestoreHints(hints) {
  stepDone[1] = true;
  stepDone[2] = Boolean(hints.has_outline);
  stepDone[3] = Boolean(hints.has_template);
  stepDone[4] = Boolean(hints.slides_phase_complete);
  stepDone[5] = Boolean(hints.pptx_complete);
  stepDone[6] = Boolean(hints.pptx_complete);
}

/**
 * 根据 ``progress.phase`` 与磁盘 hints 推断载入后应打开的向导步骤（1～6）。
 *
 * @param {Record<string, unknown>} progress - wizard-restore 中的 progress
 * @param {Record<string, unknown>} hints - wizard-restore 中的 hints
 * @returns {number} 1～6
 */
function inferActiveStepFromRestore(progress, hints) {
  const phase = typeof progress.phase === "string" ? progress.phase : "";

  /** @returns {number} */
  const fromHints = () => {
    if (hints.pptx_complete) return 6;
    if (hints.slides_phase_complete) return 5;
    if (hints.has_template) return 4;
    if (hints.has_outline) return 3;
    return 2;
  };

  if (phase === "error" || phase === "idle") {
    return fromHints();
  }

  switch (phase) {
    case "pptx_done":
      return 6;
    case "pptx_running":
      return 5;
    case "slides_done":
      return 5;
    case "slides_running":
    case "template_done":
      return 4;
    case "outline_done":
      return 3;
    case "parsed":
    case "uploaded":
      return 2;
    default:
      return fromHints();
  }
}

/**
 * 拉取并填充历史任务下拉框。
 *
 * @returns {Promise<void>}
 */
async function refreshJobsHistoryDropdown() {
  const sel = /** @type {HTMLSelectElement|null} */ (document.getElementById("history-job-select"));
  if (!sel) return;
  const cur = sel.value;
  const r = await fetch("/api/jobs/history");
  const data = await parseApiJson(r, "历史任务列表解析失败");
  if (!r.ok) throw new Error(String(data.error || `HTTP ${r.status}`));
  const jobs = Array.isArray(data.jobs) ? data.jobs : [];
  sel.innerHTML = `<option value="">${escapeHtml("请选择历史 job…")}</option>`;
  jobs.forEach((j) => {
    if (!j || typeof j !== "object") return;
    const id = /** @type {{ job_id?: string }} */ (j).job_id;
    if (!id || typeof id !== "string") return;
    const opt = document.createElement("option");
    opt.value = id;
    const stem = String(/** @type {{ stem?: string }} */ (j).stem || "").slice(0, 28);
    const phase = String(/** @type {{ phase?: string }} */ (j).phase || "");
    const mtime = /** @type {{ mtime?: number }} */ (j).mtime;
    const t = typeof mtime === "number" ? new Date(mtime * 1000).toLocaleString() : "";
    opt.textContent = `${stem || id.slice(0, 8)} · ${phase}${t ? ` · ${t}` : ""}`;
    opt.title = id;
    sel.appendChild(opt);
  });
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
}

/**
 * 将选定历史任务载入当前向导（正文、表单与各步状态）。
 *
 * @param {string} selectedId - job UUID
 * @returns {Promise<void>}
 */
async function restoreWizardFromHistoryJob(selectedId) {
  if (!selectedId) return;
  const seq = ++historyRestoreSeq;
  setWizardBusy(true);
  try {
    const r = await fetch(`/api/jobs/${encodeURIComponent(selectedId)}/wizard-restore`);
    const data = await parseApiJson(r, "载入历史任务解析失败");
    if (!r.ok) throw new Error(String(data.error || `HTTP ${r.status}`));
    if (seq !== historyRestoreSeq) return;

    jobId = String(data.job_id || selectedId);

    const doc =
      data.document && typeof data.document === "object"
        ? /** @type {Record<string, unknown>} */ (data.document)
        : {};
    const ta = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("document-text"));
    const docText = typeof doc.text === "string" ? doc.text : "";
    if (ta) ta.value = docText;
    syncStep1DocPreviewFromTextarea();

    const charCount = typeof doc.char_count === "number" ? doc.char_count : docText.length;
    const summ = typeof doc.source_summary === "string" ? doc.source_summary : "";
    const uploadMeta = document.getElementById("upload-meta");
    if (uploadMeta) uploadMeta.textContent = `${summ} · 任务 ${jobId} · ${charCount} 字符`;

    if (fileInputStep1) fileInputStep1.value = "";
    if (uploadFileStatusEl)
      uploadFileStatusEl.textContent = "未附加文件（历史任务仅恢复磁盘上的正文文本）";

    const meta =
      data.meta && typeof data.meta === "object"
        ? /** @type {Record<string, unknown>} */ (data.meta)
        : {};
    const llmSel = /** @type {HTMLSelectElement|null} */ (document.getElementById("llm-provider"));
    if (llmSel) {
      const p = meta.llm_provider;
      llmSel.value = typeof p === "string" ? p : "";
    }
    const maxEl = /** @type {HTMLInputElement|null} */ (document.getElementById("max-slides"));
    const tgtEl = /** @type {HTMLInputElement|null} */ (document.getElementById("target-slides"));
    if (maxEl)
      maxEl.value =
        meta.max_slides !== undefined && meta.max_slides !== null && meta.max_slides !== ""
          ? String(meta.max_slides)
          : "";
    if (tgtEl)
      tgtEl.value =
        meta.target_slides !== undefined && meta.target_slides !== null && meta.target_slides !== ""
          ? String(meta.target_slides)
          : "";
    const hs = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("html-style"));
    if (hs) hs.value = typeof meta.html_style === "string" ? meta.html_style : "";
    const dprEl = /** @type {HTMLInputElement|null} */ (document.getElementById("raster-dpr"));
    if (dprEl && meta.raster_dpr != null && meta.raster_dpr !== "") dprEl.value = String(meta.raster_dpr);
    const savePngEl = /** @type {HTMLInputElement|null} */ (document.getElementById("save-slide-png"));
    if (savePngEl) savePngEl.checked = Boolean(meta.save_slide_png);

    const hints =
      data.hints && typeof data.hints === "object"
        ? /** @type {Record<string, unknown>} */ (data.hints)
        : {};
    applyStepDoneFromRestoreHints(hints);

    const oj = data.outline_json;
    const op = typeof data.outline_plain === "string" ? data.outline_plain : "";
    if (hints.has_outline && oj != null && typeof oj === "object") {
      const sc = typeof data.slide_count === "number" ? data.slide_count : undefined;
      applyOutlineResponseToStep({
        outline_json: oj,
        outline_plain: op,
        slide_count: sc,
      });
    } else {
      resetOutlineEditorToEmpty();
      const om = document.getElementById("outline-meta");
      if (om) om.textContent = "";
    }

    const tm = document.getElementById("template-meta");
    if (tm)
      tm.textContent = hints.has_template
        ? "已从历史任务恢复：deck 模板已存在，见下方预览。"
        : "";

    const spBar = /** @type {HTMLElement|null} */ (document.getElementById("slides-progress-bar"));
    const spLbl = document.getElementById("slides-progress-label");
    if (hints.slides_phase_complete) setProgressBar(1, spLbl, spBar, "文档页面已全部完成");
    else setProgressBar(0, spLbl, spBar, "");

    const ppBar = /** @type {HTMLElement|null} */ (document.getElementById("pptx-progress-bar"));
    const ppLbl = document.getElementById("pptx-progress-label");
    const dl = /** @type {HTMLAnchorElement|null} */ (document.getElementById("download-merged"));
    if (hints.pptx_complete) {
      setProgressBar(1, ppLbl, ppBar, "PPT 已合并");
      if (dl) {
        dl.href = `/api/jobs/${jobId}/download/merged`;
        dl.classList.remove("disabled");
      }
      const fm = document.getElementById("final-meta");
      if (fm) fm.textContent = "合并稿已就绪，与 CLI 相同命名规则（含时间戳）。";
    } else {
      setProgressBar(0, ppLbl, ppBar, "");
      if (dl) {
        dl.classList.add("disabled");
        dl.href = "#";
      }
      const fm = document.getElementById("final-meta");
      if (fm) fm.textContent = "";
    }

    void refreshTemplatePreviewPane().catch(() => {});
    const progress =
      data.progress && typeof data.progress === "object"
        ? /** @type {Record<string, unknown>} */ (data.progress)
        : {};
    const targetStep = inferActiveStepFromRestore(progress, hints);
    setActiveStep(targetStep);
    showAlert(`已载入历史任务 ${jobId.slice(0, 8)}…`, "success");
  } catch (err) {
    showAlert(err instanceof Error ? err.message : String(err));
    const sel = /** @type {HTMLSelectElement|null} */ (document.getElementById("history-job-select"));
    if (sel) sel.value = "";
  } finally {
    setWizardBusy(false);
  }
}

/**
 * 弹窗内切换为「推理中」视图。
 */
function setOutlineModalPhaseRunning() {
  document.getElementById("outline-modal-running")?.classList.remove("d-none");
  document.getElementById("outline-modal-result")?.classList.add("d-none");
  document.getElementById("outline-modal-btn-close")?.classList.add("d-none");
  document.getElementById("outline-modal-btn-retry")?.classList.add("d-none");
  document.getElementById("outline-modal-btn-running-close")?.classList.remove("d-none");
  document.getElementById("outline-modal-btn-pause")?.classList.remove("d-none");
  startOutlineModalFakeProgress();
}

/**
 * 弹窗内切换为「成功」视图。
 *
 * @param {string} message - 提示文案
 */
function setOutlineModalPhaseSuccess(message) {
  finishOutlineModalFakeProgress();
  document.getElementById("outline-modal-running")?.classList.add("d-none");
  const resultEl = document.getElementById("outline-modal-result");
  const msgEl = document.getElementById("outline-modal-result-msg");
  resultEl?.classList.remove("d-none");
  if (msgEl) {
    msgEl.className = "small mb-0 text-success";
    msgEl.textContent = message;
  }
  document.getElementById("outline-modal-btn-running-close")?.classList.add("d-none");
  document.getElementById("outline-modal-btn-pause")?.classList.add("d-none");
  document.getElementById("outline-modal-btn-close")?.classList.remove("d-none");
  document.getElementById("outline-modal-btn-retry")?.classList.remove("d-none");
}

/**
 * 弹窗内切换为「失败」视图。
 *
 * @param {string} message - 错误文案
 */
function setOutlineModalPhaseError(message) {
  finishOutlineModalFakeProgress();
  document.getElementById("outline-modal-running")?.classList.add("d-none");
  const resultEl = document.getElementById("outline-modal-result");
  const msgEl = document.getElementById("outline-modal-result-msg");
  resultEl?.classList.remove("d-none");
  if (msgEl) {
    msgEl.className = "small mb-0 text-danger";
    msgEl.textContent = message;
  }
  document.getElementById("outline-modal-btn-running-close")?.classList.add("d-none");
  document.getElementById("outline-modal-btn-pause")?.classList.add("d-none");
  document.getElementById("outline-modal-btn-close")?.classList.remove("d-none");
  document.getElementById("outline-modal-btn-retry")?.classList.add("d-none");
}

/**
 * 步骤 2：请求大纲并驱动弹窗 UI（可多次调用以二次推理）。
 *
 * @returns {Promise<void>}
 */
async function runOutlineInference() {
  if (!jobId) return showAlert("请先完成「加载文档内容」");
  const modal = getOutlineModalInstance();
  if (!modal) return showAlert("无法打开弹窗：Bootstrap 未就绪。");
  if (outlineInferenceBusy) return;

  outlineInferenceBusy = true;
  setWizardBusy(true);
  setExecuteDisabled(btnOutline, true);
  setOutlineModalPhaseRunning();
  modal.show();

  const maxSlides = document.getElementById("max-slides")?.value ?? "";
  const targetSlides = document.getElementById("target-slides")?.value ?? "";
  /** @type {Record<string, number>} */
  const payload = {};
  if (maxSlides !== "") payload.max_slides = Number(maxSlides);
  if (targetSlides !== "") payload.target_slides = Number(targetSlides);

  outlineInferenceAbortController = new AbortController();
  const signal = outlineInferenceAbortController.signal;

  try {
    const r = await fetch(`/api/jobs/${jobId}/outline`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
    const data = await parseApiJson(r, "大纲接口解析失败");
    if (!r.ok) throw new Error(String(data.error || "大纲生成失败"));
    applyOutlineResponseToStep(data);
    stepDone[2] = true;
    const slideCount = typeof data.slide_count === "number" ? data.slide_count : "?";
    setOutlineModalPhaseSuccess(
      `推理完成：共 ${slideCount} 页，已写入任务目录。您可关闭本窗口，在步骤 2 左侧选择页面、右侧编辑后点「更新大纲内容」。`,
    );
    syncNavButtons();
  } catch (err) {
    const aborted =
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError");
    if (aborted) {
      setOutlineModalPhaseError("已暂停本次推理请求（已断开浏览器等待；服务端是否仍处理取决于实现）。");
      syncNavButtons();
      return;
    }
    const msg = err instanceof Error ? err.message : String(err);
    setOutlineModalPhaseError(msg);
  } finally {
    outlineInferenceAbortController = null;
    outlineInferenceBusy = false;
    setExecuteDisabled(btnOutline, false);
    setWizardBusy(false);
    syncNavButtons();
  }
}

document.getElementById("btn-outline")?.addEventListener("click", () => {
  void runOutlineInference();
});

document.getElementById("outline-modal-btn-retry")?.addEventListener("click", () => {
  void runOutlineInference();
});

document.getElementById("outline-modal-btn-close")?.addEventListener("click", () => {
  getOutlineModalInstance()?.hide();
});

document.getElementById("outline-modal-header-close")?.addEventListener("click", () => {
  getOutlineModalInstance()?.hide();
});

document.getElementById("outline-modal-btn-running-close")?.addEventListener("click", () => {
  getOutlineModalInstance()?.hide();
});

document.getElementById("outline-modal-btn-pause")?.addEventListener("click", () => {
  outlineInferenceAbortController?.abort();
});

const btnTemplate = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-template"));

/** 模版生成请求进行中 */
let templateRunBusy = false;

/** 模板弹窗示意进度条定时器 */
let templateModalFakeProgressTimer = /** @type {ReturnType<typeof setInterval>|null} */ (null);

/** @type {ReturnType<typeof bootstrap.Modal["getOrCreateInstance"]>|null} */
let templateModalCached = null;

/**
 * 清除模板弹窗示意进度动画。
 */
function clearTemplateModalFakeProgress() {
  if (templateModalFakeProgressTimer !== null) {
    clearInterval(templateModalFakeProgressTimer);
    templateModalFakeProgressTimer = null;
  }
}

/**
 * 生成进行中：从 0% 缓慢爬升至约 92%，完成后由 finishTemplateModalFakeProgress 收口。
 */
function startTemplateModalFakeProgress() {
  clearTemplateModalFakeProgress();
  const bar = document.getElementById("template-modal-progress-bar");
  if (!bar) return;
  bar.style.width = "0%";
  bar.setAttribute("aria-valuenow", "0");
  bar.classList.add("progress-bar-striped", "progress-bar-animated");
  let w = 0;
  templateModalFakeProgressTimer = setInterval(() => {
    if (w >= 92) return;
    w += Math.random() * 4 + 0.8;
    if (w > 92) w = 92;
    bar.style.width = `${w}%`;
    bar.setAttribute("aria-valuenow", String(Math.round(w)));
  }, 380);
}

/**
 * 生成结束：示意进度拉满并停止条纹动画。
 */
function finishTemplateModalFakeProgress() {
  clearTemplateModalFakeProgress();
  const bar = document.getElementById("template-modal-progress-bar");
  if (!bar) return;
  bar.style.width = "100%";
  bar.setAttribute("aria-valuenow", "100");
  bar.classList.remove("progress-bar-striped", "progress-bar-animated");
}

/**
 * 若全屏层打开，使其中 iframe 与主预览同源同步。
 */
function syncTemplateFullscreenIframeFromMain() {
  const main = /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template"));
  const fs = /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template-fullscreen"));
  const overlay = document.getElementById("template-preview-fullscreen-overlay");
  if (!main || !fs || !overlay || overlay.classList.contains("d-none")) return;
  const src = main.getAttribute("src");
  if (src) fs.src = src;
  else fs.removeAttribute("src");
}

/**
 * 同步步骤 3 预览工具栏按钮（全屏 / 关闭全屏）与禁用态。
 */
function syncTemplatePreviewFullscreenToolbar() {
  const iframe = /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template"));
  const openBtn = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-template-preview-fs-open"));
  const closeToolbarBtn = /** @type {HTMLButtonElement|null} */ (
    document.getElementById("btn-template-preview-fs-close")
  );
  const overlay = document.getElementById("template-preview-fullscreen-overlay");
  if (!iframe || !openBtn || !closeToolbarBtn || !overlay) return;

  const hasPreview = !iframe.classList.contains("d-none") && !!iframe.getAttribute("src");
  const fsOpen = !overlay.classList.contains("d-none");

  closeToolbarBtn.classList.toggle("d-none", !fsOpen);
  openBtn.disabled = !hasPreview || fsOpen;
}

/**
 * 打开文档模板全屏预览（复制当前 iframe 地址）。
 */
function openTemplatePreviewFullscreen() {
  const main = /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template"));
  const fs = /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template-fullscreen"));
  const overlay = document.getElementById("template-preview-fullscreen-overlay");
  if (!main || !fs || !overlay) return;
  const src = main.getAttribute("src");
  if (!src || main.classList.contains("d-none")) return;

  fs.src = src;
  overlay.classList.remove("d-none");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("template-fs-open");
  syncTemplatePreviewFullscreenToolbar();
}

/**
 * 关闭文档模板全屏预览并释放全屏 iframe。
 */
function closeTemplatePreviewFullscreen() {
  const overlay = document.getElementById("template-preview-fullscreen-overlay");
  const fs = /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template-fullscreen"));
  if (!overlay) return;
  overlay.classList.add("d-none");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("template-fs-open");
  if (fs) fs.removeAttribute("src");
  syncTemplatePreviewFullscreenToolbar();
}

/**
 * @returns {ReturnType<typeof bootstrap.Modal["getOrCreateInstance"]>|null}
 */
function getTemplateModalInstance() {
  const el = document.getElementById("template-run-modal");
  const B = globalThis.bootstrap;
  if (!el || !B?.Modal) return null;
  if (!templateModalCached) {
    templateModalCached = B.Modal.getOrCreateInstance(el, { backdrop: "static", keyboard: false });
  }
  return templateModalCached;
}

/**
 * 弹窗：模版生成中视图。
 */
function setTemplateModalPhaseRunning() {
  document.getElementById("template-modal-running")?.classList.remove("d-none");
  document.getElementById("template-modal-result")?.classList.add("d-none");
  document.getElementById("template-modal-btn-close")?.classList.add("d-none");
  document.getElementById("template-modal-btn-retry")?.classList.add("d-none");
  startTemplateModalFakeProgress();
}

/**
 * @param {string} message - 成功说明
 */
function setTemplateModalPhaseSuccess(message) {
  finishTemplateModalFakeProgress();
  document.getElementById("template-modal-running")?.classList.add("d-none");
  const resultEl = document.getElementById("template-modal-result");
  const msgEl = document.getElementById("template-modal-result-msg");
  resultEl?.classList.remove("d-none");
  if (msgEl) {
    msgEl.className = "small mb-0 text-success";
    msgEl.textContent = message;
  }
  document.getElementById("template-modal-btn-close")?.classList.remove("d-none");
  document.getElementById("template-modal-btn-retry")?.classList.remove("d-none");
}

/**
 * @param {string} message - 错误说明
 */
function setTemplateModalPhaseError(message) {
  finishTemplateModalFakeProgress();
  document.getElementById("template-modal-running")?.classList.add("d-none");
  const resultEl = document.getElementById("template-modal-result");
  const msgEl = document.getElementById("template-modal-result-msg");
  resultEl?.classList.remove("d-none");
  if (msgEl) {
    msgEl.className = "small mb-0 text-danger";
    msgEl.textContent = message;
  }
  document.getElementById("template-modal-btn-close")?.classList.remove("d-none");
  document.getElementById("template-modal-btn-retry")?.classList.add("d-none");
}

/**
 * 步骤 3：生成 deck 模版（弹窗进度 + 可再次设计）。
 *
 * @returns {Promise<void>}
 */
async function runDeckTemplateGeneration() {
  if (!jobId) return showAlert("请先完成「推理文档大纲」");
  if (templateRunBusy) return;
  const modal = getTemplateModalInstance();
  if (!modal) return showAlert("无法打开弹窗：Bootstrap 未就绪。");

  templateRunBusy = true;
  setWizardBusy(true);
  setExecuteDisabled(btnTemplate, true);
  setTemplateModalPhaseRunning();
  modal.show();

  const htmlStyle = document.getElementById("html-style")?.value || "";

  try {
    const r = await fetch(`/api/jobs/${jobId}/deck-template`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html_style: htmlStyle }),
    });
    const data = await parseApiJson(r, "模板接口解析失败");
    if (!r.ok) throw new Error(String(data.error || "模板生成失败"));

    const metaEl = document.getElementById("template-meta");
    const len = data.html_length;
    if (metaEl && (typeof len === "number" || typeof len === "string")) {
      metaEl.textContent = `HTML 长度 ${len} 字符`;
    }
    stepDone[3] = true;
    await refreshTemplatePreviewPane();
    const lenStr = typeof len === "number" || typeof len === "string" ? String(len) : "?";
    setTemplateModalPhaseSuccess(
      `模板已生成（约 ${lenStr} 字符），已更新下方「文档模板预览」。可关闭本窗口，或点击「再次设计」重新生成。`,
    );
    syncNavButtons();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setTemplateModalPhaseError(msg);
  } finally {
    templateRunBusy = false;
    setExecuteDisabled(btnTemplate, false);
    setWizardBusy(false);
    syncNavButtons();
  }
}

document.getElementById("btn-template")?.addEventListener("click", () => {
  void runDeckTemplateGeneration();
});

document.getElementById("template-modal-btn-retry")?.addEventListener("click", () => {
  void runDeckTemplateGeneration();
});

document.getElementById("template-modal-btn-close")?.addEventListener("click", () => {
  getTemplateModalInstance()?.hide();
});

document.getElementById("template-modal-header-close")?.addEventListener("click", () => {
  getTemplateModalInstance()?.hide();
});

document.getElementById("btn-template-preview-fs-open")?.addEventListener("click", () => {
  openTemplatePreviewFullscreen();
});

document.getElementById("btn-template-preview-fs-close")?.addEventListener("click", () => {
  closeTemplatePreviewFullscreen();
});

document.getElementById("btn-template-fs-exit")?.addEventListener("click", () => {
  closeTemplatePreviewFullscreen();
});

document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  const overlay = document.getElementById("template-preview-fullscreen-overlay");
  if (!overlay || overlay.classList.contains("d-none")) return;
  ev.preventDefault();
  closeTemplatePreviewFullscreen();
});

/**
 * 步骤 3：按行业分组的风格提示词预设（写入 html_style）。
 *
 * @type {Array<{ industry: string; items: Array<{ name: string; text: string }> }>}
 */
const HTML_STYLE_PROMPT_PRESETS = [
  {
    industry: "政企 / 政务",
    items: [
      {
        name: "庄重政务汇报",
        text:
          "庄重端正，红蓝白经典配色，留白适中；标题层级分明、对齐规整；图表配色克制统一；页脚信息克制；整体正式可信，适合政府工作报告与工作述职类演示。",
      },
    ],
  },
  {
    industry: "科技 / 互联网",
    items: [
      {
        name: "现代科技感（深色）",
        text:
          "深色沉浸背景配霓虹青色或紫色高光；几何分割线、微弱渐变与半透明卡片；数据用大号数字与简短 bullet；留白拉开模块间距；新锐克制，适合产品发布与技术方案答辩。",
      },
      {
        name: "简约亮色互联网风",
        text:
          "浅灰白底色与大留白；单一强调色（蓝或紫）；圆角卡片、柔和投影与图标化要点；排版轻快有序；适合互联网产品与运营复盘、增长汇报。",
      },
    ],
  },
  {
    industry: "金融 / 咨询",
    items: [
      {
        name: "专业商务简报",
        text:
          "深蓝或石墨灰主调，金色点缀节制使用；表格与图表对齐严谨；结论前置、论据分列；字体稳重；整体信赖感强，适合投融资路演、咨询交付与管理周报。",
      },
    ],
  },
  {
    industry: "教育 / 培训",
    items: [
      {
        name: "课堂与培训友好风",
        text:
          "高对比易读配色（如浅底深字）；标题醒目、要点编号清晰；示意插图区域留白；适度彩色区块区分章节；亲切有条理，适合课程讲义与企业内训课件。",
      },
    ],
  },
  {
    industry: "医疗 / 健康",
    items: [
      {
        name: "清爽可信医疗风",
        text:
          "白或浅蓝绿底色，强调洁净感；信息层级清晰，术语与数据对齐；图标简洁线性；避免花哨装饰；专业温和，适合科室汇报、健康科普与合规宣讲。",
      },
    ],
  },
  {
    industry: "文创 / 品牌活动",
    items: [
      {
        name: "大胆留白设计感",
        text:
          "大图留白与不对称排版；强对比标题字重；杂志风栅格；点缀色块或渐变节制出现；创意张力足但仍保持可读，适合品牌提案、设计复盘与发布会开场视觉。",
      },
    ],
  },
];

/**
 * @param {string} s - 全文
 * @param {number} maxChars - 预览最大字符数
 * @returns {string}
 */
function truncatePresetPreview(s, maxChars) {
  const t = s.trim();
  if (t.length <= maxChars) return t;
  return `${t.slice(0, maxChars)}…`;
}

/**
 * 渲染「提示词选择」弹窗中的行业与条目。
 */
function mountHtmlStylePresetPicker() {
  const groupsEl = document.getElementById("html-style-preset-groups");
  const modalEl = document.getElementById("html-style-preset-modal");
  if (!groupsEl || !modalEl) return;

  groupsEl.replaceChildren();

  HTML_STYLE_PROMPT_PRESETS.forEach((group) => {
    const section = document.createElement("section");
    section.className = "mb-4";

    const heading = document.createElement("h6");
    heading.className = "small text-secondary fw-semibold mb-2";
    heading.textContent = group.industry;

    const grid = document.createElement("div");
    grid.className = "d-grid gap-2";

    group.items.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wizard-preset-choice";

      const nameEl = document.createElement("span");
      nameEl.className = "wizard-preset-name";
      nameEl.textContent = item.name;

      const previewEl = document.createElement("span");
      previewEl.className = "wizard-preset-preview";
      previewEl.textContent = truncatePresetPreview(item.text, 118);

      btn.append(nameEl, previewEl);
      btn.addEventListener("click", () => {
        const ta = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("html-style"));
        if (ta) ta.value = item.text;
        globalThis.bootstrap?.Modal.getOrCreateInstance(modalEl).hide();
      });

      grid.appendChild(btn);
    });

    section.append(heading, grid);
    groupsEl.appendChild(section);
  });
}

document.getElementById("btn-html-style-prompt-picker")?.addEventListener("click", () => {
  const el = document.getElementById("html-style-preset-modal");
  if (!el || !globalThis.bootstrap?.Modal) return;
  globalThis.bootstrap.Modal.getOrCreateInstance(el).show();
});

const btnSlides = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-slides-start"));

document.getElementById("btn-slides-start")?.addEventListener("click", async () => {
  if (!jobId) return showAlert("请先完成「设计文档模版」");
  showSubmitNotice("设计文档页面");
  setWizardBusy(true);
  setExecuteDisabled(btnSlides, true);
  const bar = document.getElementById("slides-progress-bar");
  const label = document.getElementById("slides-progress-label");
  try {
    const r = await fetch(`/api/jobs/${jobId}/slides-html/start`, { method: "POST" });
    const data = await parseApiJson(r, "页面生成启动接口解析失败");
    if (!r.ok) throw new Error(data.error || "无法启动生成");
    await pollUntil(
      (p) => p.phase === "slides_done",
      (p) => {
        if (p.phase === "slides_running" && p.total) {
          setProgressBar(Number(p.current || 0) / Number(p.total), label, bar, String(p.message || ""));
        }
      },
    );
    setProgressBar(1, label, bar, "文档页面已全部完成");
    await refreshSlidePickerFromServer();
    stepDone[4] = true;
    showAlert("文档页面已全部生成，可点击「下一步」。", "success");
  } catch (err) {
    showAlert(err.message);
    setExecuteDisabled(btnSlides, false);
  } finally {
    setWizardBusy(false);
  }
});

const btnExport = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-export-pptx"));

document.getElementById("btn-export-pptx")?.addEventListener("click", async () => {
  if (!jobId) return showAlert("请先完成「设计文档页面」");
  const dprInput = /** @type {HTMLInputElement|null} */ (document.getElementById("raster-dpr"));
  const rasterDpr = Number(dprInput?.value ?? "10");
  if (!Number.isFinite(rasterDpr) || rasterDpr < 1) {
    return showAlert("截图 DPR 须为 ≥ 1 的数字");
  }
  showSubmitNotice("导出PPT格式");
  setWizardBusy(true);
  setExecuteDisabled(btnExport, true);
  const bar = document.getElementById("pptx-progress-bar");
  const label = document.getElementById("pptx-progress-label");
  try {
    const savePng = /** @type {HTMLInputElement|null} */ (document.getElementById("save-slide-png"));
    const r = await fetch(`/api/jobs/${jobId}/export-pptx/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        raster_dpr: rasterDpr,
        save_slide_png: Boolean(savePng?.checked),
      }),
    });
    const data = await parseApiJson(r, "导出接口解析失败");
    if (!r.ok) throw new Error(data.error || "无法启动导出");
    await pollUntil(
      (p) => p.phase === "pptx_done",
      (p) => {
        if (p.phase === "pptx_running" && p.total) {
          setProgressBar(Number(p.current || 0) / Number(p.total), label, bar, String(p.message || ""));
        }
      },
    );
    setProgressBar(1, label, bar, "PPT 已合并");
    const dl = document.getElementById("download-merged");
    dl.href = `/api/jobs/${jobId}/download/merged`;
    dl.classList.remove("disabled");
    document.getElementById("final-meta").textContent =
      "合并稿已就绪，与 CLI 相同命名规则（含时间戳）。";
    stepDone[5] = true;
    stepDone[6] = true;
    showAlert("已导出 PPT 并完成合并，可点击「下一步」进入合并文件步骤下载。", "success");
  } catch (err) {
    showAlert(err.message);
  } finally {
    setWizardBusy(false);
    setExecuteDisabled(btnExport, false);
  }
});

document.querySelectorAll("[data-go-step]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (btn.disabled) return;
    const step = Number(btn.getAttribute("data-go-step"));
    if (!Number.isFinite(step)) return;

    const pane = btn.closest("[data-wizard-pane]");
    const fromStep = pane ? Number(pane.getAttribute("data-wizard-pane")) : NaN;

    if (step === 2 && fromStep === 1 && !stepDone[1]) {
      const ok = await executeStep1Load();
      if (!ok) return;
    }

    if (step >= 2 && !jobId) {
      showAlert("请先完成「加载文档内容」步骤");
      return;
    }
    setActiveStep(step);
  });
});

document.getElementById("btn-history-job-refresh")?.addEventListener("click", () => {
  void refreshJobsHistoryDropdown().catch((err) => showAlert(err.message));
});

document.getElementById("history-job-select")?.addEventListener("change", (ev) => {
  const v = /** @type {HTMLSelectElement} */ (ev.target).value;
  if (!v) return;
  void restoreWizardFromHistoryJob(v);
});

document.getElementById("outline-bullet-add")?.addEventListener("click", () => {
  if (!outlineEditorSlides || outlineEditorActiveIndex < 0) return;
  commitOutlineFormIntoActiveSlide();
  const cur = outlineEditorSlides[outlineEditorActiveIndex];
  if (!cur) return;
  cur.bullets.push("");
  renderOutlineEditorForm();
});

document.getElementById("outline-slide-title")?.addEventListener("blur", () => {
  commitOutlineFormIntoActiveSlide();
  renderOutlineEditorList();
});

document.getElementById("outline-save-disk")?.addEventListener("click", async () => {
  if (!jobId || !outlineEditorSlides || outlineEditorSlides.length === 0) {
    return showAlert("无可保存的大纲，请先推理大纲。");
  }
  commitOutlineFormIntoActiveSlide();
  const issues = validateOutlineSlidesForSave(outlineEditorSlides);
  if (issues.length > 0) {
    showOutlineValidationModal(issues);
    return;
  }
  try {
    const r = await fetch(`/api/jobs/${jobId}/outline-json`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slides: outlineEditorSlides }),
    });
    const data = await parseApiJson(r, "保存大纲解析失败");
    if (!r.ok) throw new Error(String(data.error || "保存失败"));
    const slideCount = typeof data.slide_count === "number" ? data.slide_count : outlineEditorSlides.length;
    const meta = document.getElementById("outline-meta");
    if (meta) meta.textContent = `共 ${slideCount} 页 · 已写入任务目录 deck_outline.json / deck_outline.txt`;
    const oj = data.outline_json;
    if (oj != null && typeof oj === "object") {
      hydrateOutlineEditorFromRoot(/** @type {Record<string, unknown>} */ (oj));
    }
    showTransientCenterModal("大纲内容已更新（已写入 deck_outline.json / deck_outline.txt）。");
  } catch (err) {
    showAlert(err instanceof Error ? err.message : String(err));
  }
});

void refreshJobsHistoryDropdown().catch((err) => showAlert(err.message));

document.getElementById("wizard-transient-modal")?.addEventListener("hidden.bs.modal", () => {
  if (wizardTransientModalHideTimer !== null) {
    window.clearTimeout(wizardTransientModalHideTimer);
    wizardTransientModalHideTimer = null;
  }
});

document.getElementById("btn-slide-html-edit")?.addEventListener("click", async () => {
  if (slidePreviewActiveIndex === null || !jobId) return;
  const idx = slidePreviewActiveIndex;
  const modalEl = document.getElementById("slide-html-edit-modal");
  const ta = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("slide-html-edit-textarea"));
  const fn = document.getElementById("slide-html-edit-modal-filename");
  if (!modalEl || !ta || !globalThis.bootstrap?.Modal) return;
  try {
    const r = await fetch(`/api/jobs/${jobId}/html/slide/${idx}`);
    if (!r.ok) {
      const t = await r.text();
      throw new Error(t.trim().slice(0, 160) || `加载失败 HTTP ${r.status}`);
    }
    ta.value = await r.text();
    slideHtmlEditModalIndex = idx;
    if (fn) fn.textContent = `slide_${String(idx).padStart(3, "0")}.html`;
    globalThis.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  } catch (err) {
    showAlert(err instanceof Error ? err.message : String(err));
  }
});

document.getElementById("btn-slide-html-edit-save")?.addEventListener("click", async () => {
  if (slideHtmlEditModalIndex === null || !jobId) return;
  const idx = slideHtmlEditModalIndex;
  const ta = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("slide-html-edit-textarea"));
  const modalEl = document.getElementById("slide-html-edit-modal");
  const saveBtn = /** @type {HTMLButtonElement|null} */ (document.getElementById("btn-slide-html-edit-save"));
  if (!ta || !modalEl) return;
  if (saveBtn) saveBtn.disabled = true;
  try {
    const r = await fetch(`/api/jobs/${jobId}/html/slide/${idx}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html: ta.value }),
    });
    const data = await parseApiJson(r, "保存单页 HTML 解析失败");
    if (!r.ok) throw new Error(String(data.error || "保存失败"));
    const iframe = /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-slide"));
    if (iframe && !iframe.classList.contains("d-none") && slidePreviewActiveIndex === idx) {
      iframe.src = `/api/jobs/${jobId}/html/slide/${idx}?t=${Date.now()}`;
    }
    globalThis.bootstrap?.Modal.getInstance(modalEl)?.hide();
    const fname = typeof data.filename === "string" ? data.filename : "slide HTML";
    showAlert(`已保存 ${fname}`, "success");
  } catch (err) {
    showAlert(err instanceof Error ? err.message : String(err));
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
});

document.getElementById("slide-html-edit-modal")?.addEventListener("hidden.bs.modal", () => {
  slideHtmlEditModalIndex = null;
  const ta = /** @type {HTMLTextAreaElement|null} */ (document.getElementById("slide-html-edit-textarea"));
  if (ta) ta.value = "";
});

mountHtmlStylePresetPicker();

bindDeckTemplatePreviewIframeScroll(
  /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template")),
);
bindDeckTemplatePreviewIframeScroll(
  /** @type {HTMLIFrameElement|null} */ (document.getElementById("iframe-template-fullscreen")),
);

syncTemplatePreviewFullscreenToolbar();

setActiveStep(1);

// --- 右上角模型配置（读写 .env）---

/** @type {Record<string, string>} */
let llmSettingsCache = {};

/** @param {string} key */
function maskSecretValue(key, val) {
  if (!val) return "（未配置）";
  if (!key.endsWith("_API_KEY")) return val;
  if (val.length <= 8) return "••••••••";
  return `${val.slice(0, 4)}••••${val.slice(-4)}`;
}

/** @param {Record<string, string>} settings */
function renderLlmSettingsView(settings) {
  const dl = document.getElementById("llm-settings-view-dl");
  if (!dl) return;
  const prov = settings.LLM_PROVIDER || "ollama";
  const rows = [
    ["LLM 后端", prov],
    ["温度", settings.LLM_TEMPERATURE || "—"],
  ];
  if (prov === "ollama") {
    rows.push(
      ["OLLAMA_API_KEY", maskSecretValue("OLLAMA_API_KEY", settings.OLLAMA_API_KEY)],
      ["OLLAMA_BASE_URL", settings.OLLAMA_BASE_URL || "—"],
      ["OLLAMA_MODEL", settings.OLLAMA_MODEL || "—"],
    );
  } else {
    rows.push(
      ["DEEPSEEK_API_KEY", maskSecretValue("DEEPSEEK_API_KEY", settings.DEEPSEEK_API_KEY)],
      ["DEEPSEEK_API_BASE", settings.DEEPSEEK_API_BASE || "—"],
      ["DEEPSEEK_MODEL", settings.DEEPSEEK_MODEL || "—"],
    );
  }
  dl.innerHTML = rows
    .map(
      ([label, value]) =>
        `<dt class="col-sm-4 col-md-3">${escapeHtml(label)}</dt><dd class="col-sm-8 col-md-9">${escapeHtml(value)}</dd>`,
    )
    .join("");
}

/** @param {boolean} editing */
function setLlmSettingsEditMode(editing) {
  const viewEl = document.getElementById("llm-settings-view");
  const editEl = document.getElementById("llm-settings-edit");
  const footView = document.getElementById("llm-settings-footer-view");
  const footEdit = document.getElementById("llm-settings-footer-edit");
  if (viewEl) viewEl.classList.toggle("d-none", editing);
  if (editEl) {
    editEl.classList.toggle("d-none", !editing);
    editEl.setAttribute("aria-hidden", editing ? "false" : "true");
  }
  if (footView) {
    footView.classList.toggle("d-none", editing);
    footView.hidden = editing;
  }
  if (footEdit) {
    footEdit.classList.toggle("d-none", !editing);
    footEdit.hidden = !editing;
  }
}

/** @param {"ollama"|"deepseek"|""} provider */
function syncEnvProviderPanels(provider) {
  const oPanel = document.getElementById("env-panel-ollama");
  const dPanel = document.getElementById("env-panel-deepseek");
  const p = provider || "ollama";
  if (oPanel) oPanel.hidden = p !== "ollama";
  if (dPanel) dPanel.hidden = p !== "deepseek";
}

/**
 * @param {Record<string, string>} settings
 */
function fillLlmSettingsForm(settings) {
  const form = document.getElementById("form-llm-settings");
  if (!form) return;
  for (const [key, val] of Object.entries(settings)) {
    const el = /** @type {HTMLInputElement|HTMLSelectElement|null} */ (
      form.elements.namedItem(key)
    );
    if (el && "value" in el) el.value = val ?? "";
  }
  const prov = settings.LLM_PROVIDER || "ollama";
  syncEnvProviderPanels(prov);
  const step1Sel = document.getElementById("llm-provider");
  if (step1Sel) step1Sel.value = prov;
}

async function loadLlmSettings() {
  const hint = document.getElementById("llm-settings-auth-hint");
  try {
    const r = await fetch("/api/settings/llm");
    const data = await parseApiJson(r, "读取模型配置失败");
    if (!r.ok) throw new Error(String(data.error || "读取失败"));
    if (typeof data.env_path === "string") {
      const pathEl = document.getElementById("llm-settings-env-path");
      if (pathEl) pathEl.textContent = data.env_path;
    }
    fillLlmSettingsForm(/** @type {Record<string, string>} */ (data.settings || {}));
    llmSettingsCache = { ...(data.settings || {}) };
    renderLlmSettingsView(llmSettingsCache);
    setLlmSettingsEditMode(false);
    if (hint) {
      if (data.auth_ok) {
        hint.classList.add("d-none");
        hint.textContent = "";
      } else {
        hint.classList.remove("d-none");
        hint.textContent = String(data.auth_message || "当前配置可能无法调用 LLM");
      }
    }
  } catch (err) {
    if (hint) {
      hint.classList.remove("d-none");
      hint.textContent = err instanceof Error ? err.message : String(err);
    }
  }
}

document.getElementById("env-llm-provider")?.addEventListener("change", (ev) => {
  const t = /** @type {HTMLSelectElement} */ (ev.target);
  syncEnvProviderPanels(t.value);
});

document.getElementById("llm-settings-modal")?.addEventListener("show.bs.modal", () => {
  setLlmSettingsEditMode(false);
  loadLlmSettings();
});

document.getElementById("llm-settings-modal")?.addEventListener("hidden.bs.modal", () => {
  setLlmSettingsEditMode(false);
});

document.getElementById("btn-llm-settings-edit")?.addEventListener("click", () => {
  fillLlmSettingsForm(llmSettingsCache);
  setLlmSettingsEditMode(true);
});

document.getElementById("btn-llm-settings-cancel-edit")?.addEventListener("click", () => {
  fillLlmSettingsForm(llmSettingsCache);
  renderLlmSettingsView(llmSettingsCache);
  setLlmSettingsEditMode(false);
});

document.getElementById("form-llm-settings")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = /** @type {HTMLFormElement} */ (ev.currentTarget);
  const saveBtn = document.getElementById("btn-llm-settings-save");
  const payload = {};
  for (const key of [
    "LLM_PROVIDER",
    "LLM_TEMPERATURE",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_BASE",
    "DEEPSEEK_MODEL",
  ]) {
    const el = /** @type {HTMLInputElement|HTMLSelectElement|null} */ (form.elements.namedItem(key));
    if (el && "value" in el) payload[key] = el.value.trim();
  }
  if (saveBtn) saveBtn.disabled = true;
  try {
    const r = await fetch("/api/settings/llm", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await parseApiJson(r, "保存模型配置失败");
    if (!r.ok) throw new Error(String(data.error || "保存失败"));
    fillLlmSettingsForm(/** @type {Record<string, string>} */ (data.settings || {}));
    llmSettingsCache = { ...(data.settings || {}) };
    renderLlmSettingsView(llmSettingsCache);
    setLlmSettingsEditMode(false);
    showTransientCenterModal("模型配置已写入 .env");
    if (!data.auth_ok && data.auth_message) {
      showAlert(String(data.auth_message), "info");
    }
  } catch (err) {
    showAlert(err instanceof Error ? err.message : String(err));
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
});

loadLlmSettings();
