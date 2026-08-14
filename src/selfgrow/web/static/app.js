/* SelfGrowAgent Web 前端：fetch+ReadableStream 手写 SSE + 状态机 + 各负载渲染 + 雷达。
 *
 * 设计要点：
 * - 不用 EventSource：避免断线自动重连导致历史重放与 live 事件错位；连接时后端
 *   先重放 history，前端按事件 id 去重，刷新恢复零丢失。
 * - 状态机 phase: idle|running|waiting|done|error|submitting；提交期全面板禁用，
 *   409 视为「服务器已接收」忽略。
 * - 测评答案从 payload 的 questions 实时构建（不回显 correct 字段）。
 */
"use strict";

// ================= 全局状态 =================
const state = {
  phase: "idle",          // idle|running|waiting|done|error
  sid: null,
  goal: "",
  payload: null,          // 当前 interrupt 负载
  final: null,            // 战报 final state
  submitting: false,
  answers: new Map(),     // question_id -> option(0基)
  seen: new Set(),        // 已处理事件 id（去重）
  framework: null,        // /api/meta
};

// ================= DOM 快捷 =================
const $ = (id) => document.getElementById(id);
const el = {
  overlay: $("start-overlay"),
  goal: $("goal-input"),
  start: $("btn-start"),
  reset: $("btn-reset"),
  sid: $("sid-badge"),
  llm: $("llm-badge"),
  status: $("status-line"),
  transcript: $("transcript"),
  panel: $("panel"),
  toast: $("toast"),
};

const ROLE_NAMES = {
  diagnose: "🔮 占卜师",
  plan: "🗺️ 制图师",
  learn: "📖 讲师",
  spar: "⚔️ 陪练武士",
  review: "📜 史官",
  graduate: "📜 史官",
};

// ================= 工具 =================
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function setPhase(phase, label) {
  state.phase = phase;
  el.status.textContent = label || phase;
  el.status.className = "status-line " + phase;
}

function toast(msg, isErr) {
  el.toast.textContent = msg;
  el.toast.hidden = false;
  el.toast.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.toast.hidden = true; }, 3200);
}

async function api(path, opts) {
  const resp = await fetch(path, opts);
  if (resp.status === 409) return { _conflict: true };  // 服务器已接收上一条答案
  const text = await resp.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { /* 非 JSON */ }
  if (!resp.ok) {
    const msg = (body && body.detail) || `HTTP ${resp.status}`;
    throw new Error(msg);
  }
  return body;
}

// ================= SSE 客户端（手写解析） =================
function parseFrame(text) {
  let id = null, event = "message", dataLines = [];
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;          // 空行 / keep-alive 心跳
    if (line.startsWith("id:")) id = line.slice(3).trim();
    else if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (!dataLines.length) return null;
  try { return { id, event, data: JSON.parse(dataLines.join("\n")) }; }
  catch (_) { return null; }
}

async function connectSSE(sid, handlers) {
  let controller = new AbortController();
  state.sseAbort = controller;
  const resp = await fetch(`/api/sessions/${sid}/events`, {
    headers: { Accept: "text/event-stream" },
    signal: controller.signal,
  });
  if (!resp.ok) throw new Error(`SSE ${resp.status}`);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const ev = parseFrame(frame);
      if (ev && handlers[ev.event]) handlers[ev.event](ev);
    }
  }
}

// ================= 事件处理 =================
function handleEvent(ev) {
  if (ev.id != null && state.seen.has(ev.id)) return;
  if (ev.id != null) state.seen.add(ev.id);
  switch (ev.type) {
    case "message": appendDeltas(ev.delta || []); break;
    case "interrupt": {
      state.payload = ev.payload;
      state.answers.clear();
      setPhase("waiting", "等待作答");
      renderPanel();
      break;
    }
    case "report":
      state.final = ev.final;
      break;
    case "done":
      if (ev.status === "cancelled") { setPhase("done", "已取消"); renderCancelled(); }
      else if (ev.status === "error") { setPhase("error", "出错"); }
      else { setPhase("done", "通关完成 🎉"); renderReport(); }
      break;
    case "error":
      setPhase("error", "出错");
      renderError(ev.message || "未知错误");
      break;
  }
}

function appendDeltas(delta) {
  for (const m of delta) {
    const name = ROLE_NAMES[m.role] || m.role;
    const div = document.createElement("div");
    div.className = "msg";
    div.innerHTML = `<span class="role">${escapeHtml(name)}</span>${escapeHtml(m.content || "")}`;
    el.transcript.appendChild(div);
  }
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

function addSysLine(text) {
  const div = document.createElement("div");
  div.className = "msg sys";
  div.textContent = text;
  el.transcript.appendChild(div);
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

// ================= 面板渲染 =================
function renderPanel() {
  const p = state.payload;
  if (!p) return;
  if ("assessment" in p) renderAssessment(p.assessment);
  else if ("learn" in p) renderLearn(p.learn);
  else if ("spar" in p) renderSpar(p.spar);
  else if ("review" in p) renderReview(p.review);
  else el.panel.innerHTML = `<div class="card"><h2>未知交互</h2><pre>${escapeHtml(JSON.stringify(p, null, 2))}</pre></div>`;
}

function panelHeader(banner, title) {
  return `<div class="card hero"><h2>${escapeHtml(banner || "")} ${escapeHtml(title || "")}</h2></div>`;
}

// ---- 测评 ----
function renderAssessment(a) {
  const qs = a.questions || [];
  const rows = qs.map((q, i) => {
    const opts = (q.options || []).map((opt, oi) => {
      const checked = state.answers.get(q.id) === oi ? " checked" : "";
      return `
        <label class="option${checked}">
          <input type="radio" name="q${q.id}" value="${oi}"
            data-qid="${escapeHtml(q.id)}" data-opt="${oi}">
          <span class="opt-text">${escapeHtml(opt)}</span>
        </label>`;
    }).join("");
    return `
      <div class="question">
        <div class="scenario"><span class="qidx">Q${i + 1}</span>${escapeHtml(q.scenario || "")}</div>
        ${opts}
      </div>`;
  }).join("");
  el.panel.innerHTML = `
    ${panelHeader(a.banner, `${a.stage_label || "测评"}（共 ${qs.length} 题）`)}
    <div class="card">
      <div class="narration">${escapeHtml(a.narration || "")}</div>
      <div class="assessment-note">逐题选择你的真实做法（真实作答才能生成准确的雷达）。</div>
      ${rows}
      <div class="submit-row">
        <button id="btn-answer" class="primary big" style="flex:1">提交测评</button>
      </div>
    </div>`;
  // 绑定单选
  for (const input of el.panel.querySelectorAll("input[type=radio]")) {
    input.addEventListener("change", () => {
      state.answers.set(input.dataset.qid, Number(input.dataset.opt));
      // 高亮选中项
      input.closest(".question").querySelectorAll(".option").forEach((o) =>
        o.classList.toggle("selected", o === input.closest(".option")));
    });
  }
  $("btn-answer").addEventListener("click", () => {
    if (qs.some((q) => !state.answers.has(q.id))) {
      toast("还有题目未作答，请全部选择后再提交", true);
      return;
    }
    const body = { answers: qs.map((q) => ({ question_id: q.id, option: state.answers.get(q.id) })) };
    submit(body);
  });
}

// ---- 学习动作 ----
function renderLearn(l) {
  el.panel.innerHTML = `
    ${panelHeader(l.banner, `第 ${l.week} 关 · ${l.dimension_name}`)}
    <div class="card">
      <h3>📖 讲师讲解</h3>
      <div class="lesson-box">${escapeHtml(l.lesson || "")}</div>
      <div class="action-row">
        ${(l.options || []).map((opt, i) =>
          `<button class="act-opt" data-i="${i}">${escapeHtml(opt)}</button>`).join("")}
      </div>
    </div>`;
  for (const b of el.panel.querySelectorAll(".act-opt")) {
    b.addEventListener("click", () => submit({ value: l.options[Number(b.dataset.i)] }));
  }
}

// ---- 对线 ----
function renderSpar(s) {
  el.panel.innerHTML = `
    ${panelHeader(s.banner, `副本《${s.scenario_title}》 回合 ${(s.user_turns || 0) + 1}/${s.max_turns || 2}`)}
    <div class="card">
      <h3>🎯 目标</h3>
      <div class="lesson-box">${escapeHtml(s.scenario_goal || "")}</div>
      <h3 style="margin-top:12px">👤 NPC</h3>
      <div class="npc-bubble">${escapeHtml(s.npc_line || "")}</div>
      <label class="form-hint" for="spar-input">你的回应（怎么澄清、怎么要资源、怎么定方案）</label>
      <textarea id="spar-input" placeholder="把你想对老板说的话写下来…"></textarea>
      <div class="submit-row">
        <button id="btn-answer" class="primary" style="flex:1">出手 💪</button>
        <button id="btn-cancel" class="danger">放弃本轮</button>
      </div>
    </div>`;
  $("btn-answer").addEventListener("click", () => {
    const v = $("spar-input").value.trim();
    if (!v) { toast("先写下你的回应再出手", true); return; }
    submit({ value: v });
  });
  $("btn-cancel").addEventListener("click", () => submit({ value: "（未回应）" }));
}

// ---- 复盘 ----
function renderReview(r) {
  el.panel.innerHTML = `
    ${panelHeader(r.banner, `第 ${r.week} 关复盘 · ${r.dimension_name}`)}
    <div class="card">
      <h3>📜 史官引导</h3>
      <div class="lesson-box">${escapeHtml(r.guide || "")}</div>
      <label class="form-hint" for="review-input">写下你的复盘反思</label>
      <textarea id="review-input" placeholder="这一关你经历了什么？注意到什么？提炼出什么原则？下周怎么用？"></textarea>
      <div class="submit-row">
        <button id="btn-answer" class="primary" style="flex:1">沉淀复盘 ✍️</button>
        <button id="btn-cancel" class="danger">跳过</button>
      </div>
    </div>`;
  $("btn-answer").addEventListener("click", () => submit({ value: $("review-input").value.trim() || "（未填写）" }));
  $("btn-cancel").addEventListener("click", () => submit({ value: "（未填写）" }));
}

// ---- 提交（防双提交：409 视为已接收） ----
async function submit(body) {
  if (state.submitting) return;
  state.submitting = true;
  setPhase("running", "处理中…");
  disablePanel(true);
  try {
    const r = await api(`/api/sessions/${state.sid}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r._conflict) {
      state.payload = null;
      state.answers.clear();
      el.panel.innerHTML = `<div class="card"><h2>⏳ 学习中…</h2><div class="lesson-box">系统正在推进流程，请稍候。</div></div>`;
    }
  } catch (e) {
    setPhase("waiting", "等待作答");
    toast("提交失败：" + e.message, true);
    renderPanel();  // 恢复表单（保留已填内容）
    state.submitting = false;
    disablePanel(false);
  }
}

function disablePanel(on) {
  for (const b of el.panel.querySelectorAll("button, textarea, input")) b.disabled = on;
}

// ================= 战报 =================
function dimName(id) {
  if (state.framework && state.framework.dimensionMap) return state.framework.dimensionMap[id] || id;
  return id;
}

function renderReport() {
  const f = state.final;
  if (!f || !f.report) return;
  const r = f.report;
  const improved = (r.improved || []).map((x) => `<span class="chip ok">✅ ${escapeHtml(x)}</span>`).join("");
  const gaps = (r.remaining_gaps || []).map((x) => `<span class="chip warn">🔸 ${escapeHtml(x)}</span>`).join("")
    || `<span class="chip muted">无（本轮全维度达标）</span>`;
  const tools = (r.tools_used || []).map((x) => `<span class="chip muted">${escapeHtml(x)}</span>`).join("");
  const planWeeks = ((f.plan && f.plan.weeks) || []).map((w, i) => {
    const done = (i + 1) <= (f.current_week || 0);
    return `
      <div class="week-row">
        <span class="wk">W${i + 1}</span>
        <span class="dim">${escapeHtml(dimName(w.dimension))}</span>
        <span class="goal">${escapeHtml(w.goal || "")}</span>
        ${done ? '<span class="check">✔</span>' : '<span class="pending">进行中/待定</span>'}
      </div>`;
  }).join("");

  const feedback = f.spar_feedback || {};
  const sf = `
    <div class="feedback-block">综合等级：<b>L${feedback.overall_level ?? "?"} / 5</b>
      ${feedback.mistakes ? `\n待磨刀：${escapeHtml(feedback.mistakes)}` : ""}
      ${feedback.suggestions ? `\n建议：${escapeHtml(feedback.suggestions)}` : ""}
    </div>`;

  el.panel.innerHTML = `
    <div class="card hero">
      <h2>🎓 通关战报</h2>
      <div class="narration">${escapeHtml(r.summary || "")}</div>
    </div>
    <div class="stats">
      <div class="stat done"><div class="num">${r.xp ?? 0}</div><div class="lbl">XP</div></div>
      <div class="stat done"><div class="num">L${r.level ?? 1}</div><div class="lbl">成长等级</div></div>
      <div class="stat"><div class="num">${(r.improved || []).length}</div><div class="lbl">已提升维度</div></div>
      <div class="stat"><div class="num">${(r.remaining_gaps || []).length}</div><div class="lbl">仍待修炼</div></div>
    </div>
    <div class="card">
      <h3>📡 能力雷达 · 成长对比（灰 = 入关时，蓝 = 通关后）</h3>
      <div class="radar-legend">
        <span><span class="dot before"></span>入关时</span>
        <span><span class="dot after"></span>通关后</span>
      </div>
      <div class="radar-wrap"><canvas id="radar-canvas"></canvas></div>
    </div>
    <div class="card">
      <h3>✅ 已提升 / 🔸 仍待修炼</h3>
      <div class="chips">${improved}${gaps}</div>
    </div>
    <div class="card">
      <h3>🗺️ 闯关路线</h3>
      ${planWeeks}
    </div>
    ${feedback.overall_level != null ? `<div class="card"><h3>⚔️ 陪练反馈</h3>${sf}</div>` : ""}
    <div class="card">
      <h3>🔧 工具调用留痕</h3>
      <div class="chips">${tools}</div>
    </div>
    <div class="boundary">本结果为<b>辅助学习建议</b>，不替代正式测评、学校/机构评价或专业心理咨询；
      全部数据为自建模拟数据，不涉及真实个人信息。</div>
    <div class="submit-row">
      <button id="btn-again" class="primary big" style="flex:1">开启新会话 🔄</button>
    </div>`;
  $("btn-again").addEventListener("click", resetAll);
  drawRadar(r.radar_before || {}, r.radar_after || {}, state.framework.dimensionList || []);
}

function renderCancelled() {
  el.panel.innerHTML = `
    <div class="card hero"><h2>⏹ 会话已取消</h2>
      <div class="narration">本次成长练习已中止。可开启新会话重新开始。</div></div>
    <div class="submit-row"><button id="btn-again" class="primary big" style="flex:1">重新开始</button></div>`;
  $("btn-again").addEventListener("click", resetAll);
}

function renderError(msg) {
  el.panel.innerHTML = `
    <div class="card hero" style="border-color:var(--err)">
      <h2>⚠️ 出错了</h2>
      <div class="narration">${escapeHtml(msg)}</div></div>
    <div class="submit-row"><button id="btn-again" class="primary big" style="flex:1">重试 / 新会话</button></div>`;
  $("btn-again").addEventListener("click", resetAll);
}

// ================= 雷达 canvas =================
function drawRadar(before, after, dims) {
  const canvas = $("radar-canvas");
  if (!canvas || !dims || dims.length < 3) return;
  const size = 320, pad = 46, center = size / 2;
  const radius = center - pad;
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const n = dims.length;
  const pt = (i, val) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return [center + Math.cos(ang) * radius * val / 5, center + Math.sin(ang) * radius * val / 5];
  };
  const poly = (vals) => vals.map((v, i) => pt(i, v));

  // 网格：5 层同心多边形 + 轴线
  ctx.clearRect(0, 0, size, size);
  ctx.strokeStyle = "rgba(147,160,189,.28)";
  ctx.fillStyle = "rgba(147,160,189,.55)";
  ctx.lineWidth = 1;
  for (let lv = 1; lv <= 5; lv++) {
    ctx.beginPath();
    poly(Array(n).fill(lv)).forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.stroke();
  }
  for (let i = 0; i < n; i++) {
    const [x, y] = pt(i, 5);
    ctx.beginPath();
    ctx.moveTo(center, center);
    ctx.lineTo(x, y);
    ctx.stroke();
    // 维度名（中文名，短名截断）
    const label = dims[i].length > 5 ? dims[i].slice(0, 4) : dims[i];
    const [lx, ly] = pt(i, 5.4);
    ctx.fillStyle = "var(--muted)";
    ctx.font = "12px 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, lx, ly);
  }

  const drawPoly = (vals, color, fillAlpha) => {
    const pts = poly(vals);
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.globalAlpha = fillAlpha;
    ctx.fill();
    ctx.globalAlpha = 1;
  };

  const afterVals = dims.map((d) => after[d] || 1);
  const beforeVals = dims.map((d) => before[d] || 1);
  drawPoly(beforeVals, "rgba(147,160,189,.75)", 0.12);   // 灰色 = 入关时
  drawPoly(afterVals, "#4f8cff", 0.20);                  // 蓝色 = 通关后
}

// ================= 会话生命周期 =================
async function startRun(goal) {
  state.goal = goal;
  setPhase("running", "正在启动…");
  el.overlay.classList.add("hidden");
  disablePanel(true);
  try {
    const r = await api("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal }),
    });
    state.sid = r.session_id;
    state.seen.clear();
    el.sid.textContent = r.session_id;
    el.sid.classList.add("live");
    history.replaceState(null, "", "?sid=" + r.session_id);
    addSysLine("会话已创建：" + r.session_id);
    await connectSSE(r.session_id, { message: handleEvent, interrupt: handleEvent, report: handleEvent, done: handleEvent, error: handleEvent });
  } catch (e) {
    setPhase("error", "启动失败");
    toast("启动失败：" + e.message, true);
    el.overlay.classList.remove("hidden");
  }
}

function resetAll() {
  if (state.sseAbort) state.sseAbort.abort();
  state.phase = "idle";
  state.sid = null;
  state.payload = null;
  state.final = null;
  state.answers.clear();
  state.seen.clear();
  el.transcript.innerHTML = "";
  el.panel.innerHTML = "";
  el.sid.textContent = "-";
  el.sid.classList.remove("live");
  el.goal.value = "";
  history.replaceState(null, "", location.pathname);
  el.overlay.classList.remove("hidden");
  setPhase("idle", "就绪");
}

// 刷新恢复：有 ?sid= 时按快照恢复界面
async function recoverFromUrl() {
  const q = new URLSearchParams(location.search);
  const sid = q.get("sid");
  if (!sid) return;
  try {
    const snap = await api(`/api/sessions/${sid}`);
    state.sid = sid;
    el.sid.textContent = sid;
    el.sid.classList.add("live");
    el.overlay.classList.add("hidden");
    // 重放历史（转录 + 终态）
    for (const ev of snap.history || []) handleEvent(ev);
    if (snap.final) { state.final = snap.final; }
    // 若仍在等待，立即渲染当前负载
    if (snap.status === "waiting" && snap.current_payload) {
      state.payload = snap.current_payload;
      setPhase("waiting", "等待作答");
      renderPanel();
    } else if (snap.status === "done" && snap.final) {
      renderReport();
    } else if (snap.status === "cancelled") {
      renderCancelled();
    } else if (snap.status === "error") {
      renderError("会话运行出错");
    }
    // 恢复 SSE 实时流（后端重放 + 去重）
    connectSSE(sid, { message: handleEvent, interrupt: handleEvent, report: handleEvent, done: handleEvent, error: handleEvent })
      .catch((e) => { if (e.name !== "AbortError") console.warn("SSE 恢复失败", e); });
  } catch (_) {
    toast("会话已失效，请重新开始", true);
  }
}

// ================= 启动 =================
async function init() {
  try {
    const meta = await api("/api/meta");
    state.framework = meta;
    state.framework.dimensionMap = {};
    state.framework.dimensionList = (meta.dimensions || []).map((d) => {
      state.framework.dimensionMap[d.id] = d.name;
      return d.id;
    });
    el.llm.textContent = "模型：" + (meta.llm_mode === "claude" ? "Claude" : "Mock 离线");
    el.llm.classList.add("live");
  } catch (e) {
    el.llm.textContent = "模型：未知";
  }
  el.start.addEventListener("click", () => {
    const goal = el.goal.value.trim();
    if (!goal) { toast("先输入你的学习诉求", true); return; }
    startRun(goal);
  });
  el.reset.addEventListener("click", resetAll);
  await recoverFromUrl();
}

document.addEventListener("DOMContentLoaded", init);
