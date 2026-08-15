/* SelfGrowAgent Web 前端：文字冒险 / 视觉小说（VN）界面。
 *
 * 设计要点：
 * - 不用 EventSource：避免断线自动重连导致历史重放与 live 事件错位；连接时后端
 *   先重放 history，前端按事件 id 去重，刷新恢复零丢失。
 * - 状态机 phase: idle|running|waiting|done|error；提交期 locked 全面板禁用，
 *   409 视为「服务器已接收」忽略。
 * - 每个 interrupt 携带 hud（旅程点/周/XP/等级），前端据此刷新 HUD。
 * - 测评逐题一问一答：叙事打字机 → 对话匣 → ▼ 选项，作答 {question_id, option}。
 * - 对线副本：BOSS 名牌 + 压力条 + 利害 + 自由输入。
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
  answers: new Map(),     // question_id -> option(0基)（兼容保留）
  seen: new Set(),        // 已处理事件 id（去重）
  hud: null,              // 最近一次 HUD（journey/xp/level）
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
  status: $("status-line"),
  toast: $("toast"),
  sceneBg: $("scene-bg"),
  sceneTitle: $("scene-title"),
  hudBoss: $("hud-boss"),
  bossLine: $("boss-line"),
  pressureBar: $("pressure-bar"),
  narration: $("narration"),
  nameplate: $("nameplate"),
  dialogueBox: $("dialogue-box"),
  dialogueText: $("dialogue-text"),
  choices: $("choices"),
  inputArea: $("input-area"),
  journal: $("journal"),
  journeyDots: $("journey-dots"),
  xpFill: $("xp-fill"),
  xpLabel: $("xp-label"),
  levelBadge: $("level-badge"),
  stageInner: $("stage").querySelector(".stage-inner"),
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

function dimName(id) {
  if (state.framework && state.framework.dimensionMap) return state.framework.dimensionMap[id] || id;
  return id;
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
      // 注意：parseFrame 返回的是帧 {id,event,data}，data 才是会话事件 dict（含 type）
      if (ev && handlers[ev.event]) handlers[ev.event](ev.data);
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
    div.innerHTML = `<span class="j-role">${escapeHtml(name)}</span> ${escapeHtml(m.content || "")}`;
    el.journal.appendChild(div);
  }
  el.journal.scrollTop = el.journal.scrollHeight;
}

function addSysLine(text) {
  const div = document.createElement("div");
  div.className = "j-sys";
  div.textContent = text;
  el.journal.appendChild(div);
  el.journal.scrollTop = el.journal.scrollHeight;
}

// ================= 场景 / 打字机 =================
function mapMood(s) {
  if (!s) return "mystic";
  if (/副本|对线|战斗|boss/i.test(s)) return "boss";
  if (/复盘|史官|肃穆/i.test(s)) return "review";
  if (/报告|结算/i.test(s)) return "report";
  if (/讲|学|练|研/i.test(s)) return "study";
  return "mystic";
}

function setScene({ mood, title }) {
  el.sceneBg.className = "mood-" + mapMood(mood);
  el.sceneTitle.textContent = title || "—";
}

function clearStage() {
  const settle = $("settle");
  if (settle) settle.remove();
  el.hudBoss.hidden = true;
  el.nameplate.hidden = true;
  el.dialogueBox.hidden = true;
  el.choices.innerHTML = "";
  el.inputArea.hidden = true;
  el.inputArea.innerHTML = "";
  el.narration.textContent = "";
}

function typeText(el2, text, done) {
  if (!text) { if (done) done(); return; }
  el2.textContent = "";
  let i = 0, timer = null, finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    el2.textContent = text;
    if (done) done();
  };
  const step = () => {
    if (i < text.length) { el2.textContent += text[i++]; timer = setTimeout(step, 13); }
    else finish();
  };
  el2.addEventListener("click", finish, { once: true });  // 点击跳过打字
  timer = setTimeout(step, 80);
}

function showChoices(items) {
  el.choices.innerHTML = "";
  items.forEach((it, i) => {
    const b = document.createElement("button");
    b.className = "choice-btn";
    b.textContent = it.label;
    b.style.animationDelay = (0.08 + i * 0.07).toFixed(2) + "s";
    b.addEventListener("click", it.onClick);
    el.choices.appendChild(b);
  });
}

function showInput({ label, placeholder, submitText, skipText, allowEmpty, onSubmit, onSkip }) {
  el.inputArea.innerHTML = `
    <label>${escapeHtml(label || "")}</label>
    <textarea id="free-input" placeholder="${escapeHtml(placeholder || "")}"></textarea>
    <div class="submit-row">
      <button id="btn-send" class="primary">${escapeHtml(submitText || "提交")}</button>
      ${skipText ? `<button id="btn-skip" class="danger">${escapeHtml(skipText)}</button>` : ""}
    </div>`;
  el.inputArea.hidden = false;
  $("btn-send").addEventListener("click", () => {
    const v = $("free-input").value.trim();
    if (!v && !allowEmpty) { toast("先写下你的回应再出手", true); return; }
    onSubmit(v);
  });
  if (skipText) $("btn-skip").addEventListener("click", () => onSkip && onSkip());
}

function showThinking() {
  clearStage();
  el.narration.textContent = "⏳ 系统正在推进剧情…";
}

// ================= HUD：旅程点 / XP / 等级 =================
function updateHud(hud) {
  if (!hud) return;
  state.hud = hud;
  renderXp(hud.xp || 0);
  renderJourney(hud);
}

function renderXp(xp) {
  const level = 1 + Math.floor((xp || 0) / 50);
  const into = (xp || 0) % 50;
  el.xpFill.style.width = Math.min(100, (into / 50) * 100) + "%";
  el.xpLabel.textContent = `${xp || 0} XP`;
  el.levelBadge.textContent = `L${level}`;
}

function renderJourney(hud) {
  const total = hud.total_weeks || 0;
  const dots = [{ label: "诊断" }];
  if (total > 0) dots.push({ label: "规划" });
  for (let i = 1; i <= total; i++) dots.push({ label: `W${i}` });
  if (total > 0) dots.push({ label: "毕业" });
  // 规划尚未揭晓（基线测评中）：旅程条先用幽灵占位「诊断 → 规划 → … → 毕业」
  if (total <= 0) dots.push({ label: "规划", ghost: true },
                            { label: "…", ghost: true },
                            { label: "毕业", ghost: true });

  let cur = -1;
  const stage = hud.stage;
  if (state.final) cur = dots.length - 1;         // 已毕业 → 全点亮
  else if (stage === "diagnose") cur = 0;
  else if (stage === "plan") cur = 1;
  else if (stage === "learn" || stage === "spar" || stage === "review")
    cur = Math.min(1 + (hud.week || 1), dots.length - 1);

  el.journeyDots.innerHTML = dots.map((d, i) =>
    `<span class="${d.ghost ? "dot ghost" : i < cur ? "dot done" : i === cur ? "dot cur" : "dot"}"><em>${escapeHtml(d.label)}</em></span>`
  ).join("");
}

// ================= 面板渲染（VN） =================
function renderPanel() {
  const p = state.payload;
  if (!p) return;
  if ("assessment" in p) { updateHud(p.assessment.hud); renderAssessment(p.assessment); }
  else if ("learn" in p) { updateHud(p.learn.hud); renderLearn(p.learn); }
  else if ("spar" in p) { updateHud(p.spar.hud); renderSpar(p.spar); }
  else if ("review" in p) { updateHud(p.review.hud); renderReview(p.review); }
  else {
    setScene({ mood: "mystic", title: "未知事件" });
    clearStage();
    el.dialogueBox.hidden = false;
    el.dialogueText.textContent = JSON.stringify(p, null, 2);
  }
}

// ---- 测评（逐题一问一答） ----
function renderAssessment(a) {
  const q = a.question || {};
  const idx = (a.index || 0) + 1;
  const total = a.total || 1;
  const dim = dimName(q.dimension);
  setScene({
    mood: (a.scene || {}).mood,
    title: `${a.stage_label || "测评"} · ${dim} · 第 ${idx}/${total} 题`,
  });
  clearStage();
  el.nameplate.textContent = ROLE_NAMES[a.role] || a.banner || "占卜师";
  el.nameplate.hidden = false;
  el.dialogueBox.hidden = false;
  setPhase("waiting", `等待作答 · 第 ${idx}/${total} 题`);
  typeText(el.narration, a.narration || "", () => {
    typeText(el.dialogueText, q.scenario || "", () => {
      showChoices((q.options || []).map((opt, oi) => ({
        label: opt,
        onClick: () => submit({ question_id: q.id, option: oi }),
      })));
    });
  });
}

// ---- 拜师学艺 ----
function renderLearn(l) {
  setScene({ mood: "study", title: `拜师学艺 · W${l.week} · ${l.dimension_name}` });
  clearStage();
  el.nameplate.textContent = "📖 讲师";
  el.nameplate.hidden = false;
  el.dialogueBox.hidden = false;
  setPhase("waiting", `等待选择 · W${l.week}`);
  const quest = [l.milestone, l.challenge].filter(Boolean).join("\n");
  typeText(el.narration, quest ? "◈ 本周任务\n" + quest : "", () => {
    typeText(el.dialogueText, l.lesson || "", () => {
      showChoices((l.options || []).map((opt) => ({
        label: opt,
        onClick: () => submit({ value: opt }),
      })));
    });
  });
}

// ---- 副本对线（BOSS HUD） ----
function renderSpar(s) {
  const turn = (s.user_turns || 0) + 1;
  const maxTurns = s.max_turns || 2;
  setScene({ mood: "boss", title: `副本《${s.scene_title || ""}》 · 回合 ${turn}/${maxTurns}` });
  clearStage();
  const boss = s.boss || {};
  el.hudBoss.hidden = false;
  el.bossLine.innerHTML = `
    <span class="boss-name">☠ ${escapeHtml(boss.name || "上级")}</span>
    <span class="boss-role">${escapeHtml(boss.role || "")}</span>
    <span class="boss-style">${escapeHtml(boss.style || "")}</span>
    <span class="boss-persona">${escapeHtml(boss.persona || "")}</span>
    <span class="turns">回合 ${turn}/${maxTurns}</span>`;
  const now = Math.max(0, Math.min(5, s.pressure_now || 0));
  let segs = "";
  for (let i = 0; i < 5; i++) segs += `<span class="seg${i < now ? " on" : ""}"></span>`;
  el.pressureBar.innerHTML = segs + `<span class="plabel">压力 ${now}/5</span>`;
  setPhase("waiting", `副本对线 · 回合 ${turn}/${maxTurns}`);
  const env = s.environment ? `场景：${s.environment}` : "";
  const stakes = s.stakes ? `利害：${s.stakes}` : "";
  typeText(el.narration, [env, stakes].filter(Boolean).join("\n"), () => {
    el.nameplate.textContent = boss.name || "上级";
    el.nameplate.hidden = false;
    el.dialogueBox.hidden = false;
    typeText(el.dialogueText, s.npc_line || "", () => {
      showInput({
        label: "你的回应（怎么谈、怎么争取、怎么定方案）",
        placeholder: "把你想对老板说的话写下来…",
        submitText: "出手 💪",
        skipText: "放弃本轮",
        onSubmit: (v) => submit({ value: v || "（未回应）" }),
        onSkip: () => submit({ value: "（未回应）" }),
      });
    });
  });
}

// ---- 史官复盘 ----
function renderReview(r) {
  setScene({ mood: "review", title: `史官复盘 · W${r.week} · ${r.dimension_name}` });
  clearStage();
  el.nameplate.textContent = "📜 史官";
  el.nameplate.hidden = false;
  el.dialogueBox.hidden = false;
  setPhase("waiting", `等待复盘 · W${r.week}`);
  typeText(el.narration, `第 ${r.week} 关已结束，复盘沉淀 +50 XP。`, () => {
    typeText(el.dialogueText, r.guide || "", () => {
      showInput({
        label: "写下你的复盘反思",
        placeholder: "这一关你经历了什么？注意到什么？提炼出什么原则？下周怎么用？",
        submitText: "沉淀复盘 ✍️",
        skipText: "跳过",
        allowEmpty: true,
        onSubmit: (v) => submit({ value: v || "（未填写）" }),
        onSkip: () => submit({ value: "（未填写）" }),
      });
    });
  });
}

// ---- 提交（防双提交：409 视为已接收） ----
async function submit(body) {
  if (state.submitting) return;
  state.submitting = true;
  setPhase("running", "处理中…");
  showThinking();
  try {
    const r = await api(`/api/sessions/${state.sid}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r._conflict) {
      state.payload = null;
      state.answers.clear();
    }
  } catch (e) {
    setPhase("waiting", "等待作答");
    toast("提交失败：" + e.message, true);
    renderPanel();  // 恢复当前场景（保留已填内容）
  } finally {
    state.submitting = false;
  }
}

// ================= 通关战报（结算） =================
function renderReport() {
  const f = state.final;
  if (!f || !f.report) return;
  const r = f.report;
  updateHud({
    stage: "graduate",
    week: f.current_week || 0,
    total_weeks: (f.plan && f.plan.total_weeks) || 0,
    xp: r.xp || 0,
    level: r.level || 1,
  });
  setScene({ mood: "report", title: "通关结算" });
  clearStage();

  const improved = (r.improved || []).map((x) => `<span class="chip ok">✅ ${escapeHtml(x)}</span>`).join("");
  const gaps = (r.remaining_gaps || []).map((x) => `<span class="chip warn">🔸 ${escapeHtml(x)}</span>`).join("")
    || `<span class="chip muted">无（本轮全维度达标）</span>`;
  const tools = (r.tools_used || []).map((x) => `<span class="chip muted">${escapeHtml(x)}</span>`).join("");
  const planWeeks = ((f.plan && f.plan.weeks) || []).map((w, i) => {
    const done = (i + 1) <= (f.current_week || 0);
    const actions = (w.actions || []).map((a) =>
      `<div class="actions">• ${escapeHtml(a.criterion || a || "")}</div>`).join("");
    const link = w.scenario_link ? `<div class="link">${escapeHtml(w.scenario_link)}</div>` : "";
    return `
      <div class="week-row">
        <div class="wk-line"><span class="wk">W${i + 1}</span>
          <span class="dim">${escapeHtml(dimName(w.dimension))}</span>
          <span class="goal">${escapeHtml(w.goal || "")}</span>
          ${done ? '<span class="check">✔</span>' : '<span class="pending">待定</span>'}
        </div>
        ${w.milestone ? `<div class="milestone">${escapeHtml(w.milestone)}</div>` : ""}
        ${actions}
        ${link}
      </div>`;
  }).join("");

  const feedback = f.spar_feedback || {};
  const sf = `
    <div class="feedback-block">综合等级：<b>L${feedback.overall_level ?? "?"} / 5</b>
      ${feedback.mistakes ? `\n待磨刀：${escapeHtml(feedback.mistakes)}` : ""}
      ${feedback.suggestions ? `\n建议：${escapeHtml(feedback.suggestions)}` : ""}
    </div>`;

  settle(`
    <div class="card hero">
      <h2>🎓 通关战报</h2>
      <div class="sub">${escapeHtml(r.goal || "")}</div>
      <div class="lesson-box" style="margin-top:10px">${escapeHtml(r.summary || "")}</div>
    </div>
    <div class="stats">
      <div class="stat done"><div class="num">${r.xp ?? 0}</div><div class="lbl">XP</div></div>
      <div class="stat done"><div class="num">L${r.level ?? 1}</div><div class="lbl">成长等级</div></div>
      <div class="stat"><div class="num">${(r.improved || []).length}</div><div class="lbl">已提升维度</div></div>
      <div class="stat"><div class="num">${(r.remaining_gaps || []).length}</div><div class="lbl">仍待修炼</div></div>
    </div>
    <div class="card">
      <h3>📡 能力雷达 · 成长对比（灰 = 入关时，金 = 通关后）</h3>
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
      <div class="chips">${tools || '<span class="chip muted">无</span>'}</div>
    </div>
    <div class="boundary">本结果为<b>辅助学习建议</b>，不替代正式测评、学校/机构评价或专业心理咨询；
      全部数据为自建模拟数据，不涉及真实个人信息。</div>
    <div class="submit-row">
      <button id="btn-again" class="primary big" style="flex:1">开启新会话 🔄</button>
    </div>`);
  $("btn-again").addEventListener("click", resetAll);
  drawRadar(r.radar_before || {}, r.radar_after || {}, state.framework.dimensionList || []);
}

function renderCancelled() {
  setScene({ mood: "review", title: "会话中止" });
  clearStage();
  settle(`
    <div class="card hero"><h2>⏹ 会话已取消</h2>
      <div class="narration" style="cursor:default">本次成长练习已中止。可开启新会话重新开始。</div></div>
    <div class="submit-row"><button id="btn-again" class="primary big" style="flex:1">重新开始</button></div>`);
  $("btn-again").addEventListener("click", resetAll);
}

function renderError(msg) {
  setScene({ mood: "review", title: "出错了" });
  clearStage();
  settle(`
    <div class="card hero" style="border-color:var(--err)">
      <h2>⚠️ 出错了</h2>
      <div class="narration" style="cursor:default">${escapeHtml(msg)}</div></div>
    <div class="submit-row"><button id="btn-again" class="primary big" style="flex:1">重试 / 新会话</button></div>`);
  $("btn-again").addEventListener("click", resetAll);
}

function settle(html) {
  const wrap = document.createElement("div");
  wrap.id = "settle";
  wrap.className = "settle-wrap";
  wrap.innerHTML = html;
  el.stageInner.appendChild(wrap);
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
    ctx.fillStyle = "var(--ink-dim)";
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
  drawPoly(beforeVals, "rgba(179,171,146,.8)", 0.12);   // 灰 = 入关时
  drawPoly(afterVals, "#e0a83c", 0.22);                 // 金 = 通关后
}

// ================= 会话生命周期 =================
async function startRun(goal) {
  state.goal = goal;
  setPhase("running", "正在启动…");
  el.overlay.classList.add("hidden");
  showThinking();
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
  state.hud = null;
  state.answers.clear();
  state.seen.clear();
  el.journal.innerHTML = "";
  clearStage();
  el.sid.textContent = "-";
  el.sid.classList.remove("live");
  el.goal.value = "";
  el.xpFill.style.width = "0%";
  el.xpLabel.textContent = "0 XP";
  el.levelBadge.textContent = "L1";
  el.journeyDots.innerHTML = "";
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
    // 重放历史（过程记录 + 终态）
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
  } catch (e) {
    state.framework = { dimensionMap: {}, dimensionList: [] };
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
