// Seqwater Ops Command Centre. Talks to the Agent Bricks runtime (/api/invocations, SSE) and
// /api/seqwater/overview. No build step, no framework.
const md = window.markdownit({ html: false, linkify: true, breaks: false });
const $ = (id) => document.getElementById(id);
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

const state = {
  sessionId: uuid(), viewer: null, busy: false, pending: false, severity: "All", overview: null,
  draft: null, steps: null, toolSteps: new Map(), activeInsight: null, approvalCard: null,
};

const SUGGESTIONS = [
  "What do I need to know this morning?",
  "Why is Landers Shute flagged, and what should we do about it?",
  "Is the Mount Crosby Eastbank high lift pump going to fail? Raise a work order if the evidence supports it.",
  "Draft and submit the regulator notification for the Canungra E. coli detection.",
  "If Unitywater demand stays 9% above forecast and we add 60 ML/d from the desal, how long until drought readiness?",
];

const SEVERITIES = ["Critical", "High", "Medium", "Info"];
const SEV_GROUP = { Critical: "Decide today", High: "Watch closely", Medium: "On the radar", Info: "Assurance" };
const SEV_ICON = { Critical: "i-critical", High: "i-high", Medium: "i-medium", Info: "i-info" };

// [while running, when done]
const TOOL_LABELS = {
  get_morning_briefing: () => ["Reading this morning's briefing", "Read this morning's briefing"],
  list_proactive_insights: () => ["Checking proactive insights", "Checked proactive insights"],
  investigate_site: (a) => [`Investigating ${a.site || "the site"}`, `Investigated ${a.site || "the site"}`],
  water_quality_trend: (a) => [`Pulling the ${a.parameter || "water quality"} trend at ${a.site || "the site"}`, `Pulled the ${a.parameter || "water quality"} trend at ${a.site || "the site"}`],
  asset_health: (a) => [`Checking asset health for ${a.asset_or_site || "the asset"}`, `Checked asset health for ${a.asset_or_site || "the asset"}`],
  water_security_outlook: () => ["Running the water security what-if", "Ran the water security what-if"],
  energy_shift_savings: () => ["Analysing pumping energy by tariff window", "Analysed pumping energy by tariff window"],
  list_open_incidents: () => ["Checking open incidents", "Checked open incidents"],
  recent_agent_actions: () => ["Reviewing recent actions", "Reviewed recent actions"],
  get_reservoir_profile: () => ["Reading the Lake Baroon depth profile and buoys", "Read the Lake Baroon depth profile and buoys"],
  raise_work_order: () => ["Preparing a work order", "Raised the work order"],
  request_offtake_change: (a) => [`Preparing a switch to the ${(a.offtake_level || "").toLowerCase()} offtake`, `Switched Landers Shute to the ${(a.offtake_level || "").toLowerCase()} offtake`],
  submit_regulator_notification: () => ["Preparing a regulator notification", "Submitted the regulator notification"],
  send_stakeholder_briefing: () => ["Preparing a stakeholder briefing", "Sent the stakeholder briefing"],
  genie_agent_ask: (a) => {
    const q = `${(a.question || "").slice(0, 80)}${(a.question || "").length > 80 ? "…" : ""}`;
    return [`Asking Genie: ${q}`, `Asked Genie: ${q}`];
  },
  genie_agent_poll: () => ["Waiting for Genie", "Genie answered"],
  genie_agent_query_result: () => ["Fetching the Genie result", "Fetched the Genie result"],
};
const toolLabel = (call) => (TOOL_LABELS[call.name] || (() => [call.name.replaceAll("_", " "), call.name.replaceAll("_", " ")]))(call.args || {});
const ACTIONS = {
  raise_work_order: { title: "Raise work order", button: "Approve work order", noun: "Work order" },
  submit_regulator_notification: { title: "Submit regulator notification", button: "Approve notification", noun: "Notification" },
  send_stakeholder_briefing: { title: "Send stakeholder briefing", button: "Approve briefing", noun: "Briefing" },
  request_offtake_change: { title: "Switch the Landers Shute offtake", button: "Approve offtake change", noun: "Offtake change" },
};
const FIELD_LABELS = {
  asset_id: "Asset", priority: "Priority", description: "Work", justification: "Evidence", incident_id: "Incident",
  recipient: "To", notification_text: "Notification", subject: "Subject", body: "Message", offtake_level: "Offtake",
};
const ACTION_LABEL = { WORK_ORDER: "Work order", REGULATOR_NOTIFICATION: "Regulator notification", BRIEFING: "Briefing", OFFTAKE_CHANGE: "Offtake change" };
const SITE_ICON = { Dam: "dam", "Water Treatment Plant": "wtp", "Advanced Water Treatment Plant": "wtp", "Desalination Plant": "desal", "Pump Station": "pump" };
const TWIN_SITES = new Set(["BPD", "LSW"]);

// ------------------------------------------------------------------ helpers
const n0 = (v) => (v == null || isNaN(v) ? "–" : Math.round(Number(v)).toLocaleString("en-AU"));
const n1 = (v) => (v == null || isNaN(v) ? "–" : Number(v).toLocaleString("en-AU", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
const money = (v) => {
  if (v == null || isNaN(v) || Number(v) === 0) return "";
  const x = Math.abs(Number(v));
  return x >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : x >= 1e3 ? `$${Math.round(v / 1e3)}k` : `$${Math.round(v)}`;
};
const bne = (iso, opts) => (iso ? new Date(iso).toLocaleString("en-AU", { timeZone: "Australia/Brisbane", ...opts }) : "");
const textOf = (c) => (typeof c === "string" ? c : Array.isArray(c) ? c.map((x) => (typeof x === "string" ? x : x?.text || "")).join("") : "");
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};
const icon = (id, cls = "icon") => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("class", cls);
  s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#${id}`);
  s.append(u);
  return s;
};
const sevBadge = (sev) => {
  const b = el("span", `sev sev-${sev.toLowerCase()}`);
  b.append(icon(SEV_ICON[sev] || "i-info"), document.createTextNode(sev));
  return b;
};

// Models like emoji severity markers; render them as the same badges the rest of the UI uses.
const EMOJI = { "🔴": "Critical", "🟠": "High", "🟡": "Medium", "🟢": "Info" };
function renderMd(text) {
  let html = md.render(text || "");
  html = html.replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, "</table></div>");
  for (const [e, sev] of Object.entries(EMOJI)) {
    html = html.split(e).join(`<span class="sev sev-${sev.toLowerCase()}">${sev}</span>`);
  }
  // any other emoji the model adds (e.g. 🚨, ✅) is dropped: the UI uses badges and icons, not emoji
  return html.replace(/\p{Extended_Pictographic}\uFE0F?/gu, "");
}

// ------------------------------------------------------------------ overview
function skeleton() {
  $("status").replaceChildren(...Array.from({ length: 7 }, () => {
    const m = el("div", "metric");
    m.append(el("span", "skel"), el("span", "skel"));
    m.lastChild.style.width = "60%";
    return m;
  }));
  const box = el("div");
  for (let i = 0; i < 4; i++) {
    const row = el("div", "insight");
    row.append(el("span", "skel"), el("span", "skel"), el("span", "skel"));
    row.lastChild.style.width = "40%";
    box.append(row);
  }
  $("insights").replaceChildren(box);
}

async function loadOverview(fresh = false) {
  try {
    const r = await fetch(`/api/seqwater/overview${fresh ? "?fresh=true" : ""}`, { credentials: "same-origin" });
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || r.statusText);
    state.overview = data;
    renderMeta(data);
    renderStatus(data.kpis);
    renderFilter();
    renderInsights();
    renderActions(data.actions);
  } catch (e) {
    $("asof").textContent = "Data unavailable";
    const box = el("div", "error-box");
    box.append(
      el("p", null, `Couldn't load today's insights: ${e.message}`),
      el("p", "meta", "Check that the app can reach the SQL warehouse and the demo schema (RUNBOOK, troubleshooting)."),
    );
    const retry = el("button", "btn btn-secondary btn-sm", "Retry");
    retry.type = "button";
    retry.onclick = () => { skeleton(); loadOverview(true); };
    box.append(retry);
    $("insights").replaceChildren(box);
    $("status").replaceChildren();
  }
}

function renderMeta(d) {
  const through = d.meta?.data_through_date
    ? new Date(`${d.meta.data_through_date}T00:00:00`).toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short", year: "numeric" })
    : "";
  const raised = d.briefing?.generated_at ? bne(d.briefing.generated_at, { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
  $("asof").textContent = `Data to ${through}${raised ? ` · Insights raised ${raised}` : ""}`;
  $("insights-meta").textContent = raised ? `Raised by the proactive insights job, ${raised}` : "Raised by the proactive insights job";
  $("brief-meta").textContent = raised ? `Generated ${raised} from today's insights` : "";
}

function renderStatus(k) {
  const change = k.grid_storage_change_30d;
  const metrics = [
    { label: "Grid storage", value: `${n1(k.grid_storage_pct)}%`, note: change == null ? "" : `${change < 0 ? "Down" : "Up"} ${n1(Math.abs(change))} pts in 30 days` },
    { label: "Produced yesterday", value: `${n0(k.produced_yesterday_ml)} ML`, note: "Treated water, all plants" },
    { label: "Demand vs forecast", value: `${k.demand_vs_forecast_pct > 0 ? "+" : ""}${n1(k.demand_vs_forecast_pct)}%`, note: "Last 14 days" },
    { label: "Critical insights", value: n0(k.critical), note: `${n0(k.high)} high priority`, attention: k.critical > 0 },
    { label: "Notifications due", value: n0(k.notifications_pending), note: "To the regulator", attention: k.notifications_pending > 0 },
    { label: "Overdue PMs", value: n0(k.overdue_critical_pms), note: "Criticality A assets" },
    { label: "Avoidable energy", value: money(k.avoidable_energy_aud) || "–", note: "Per year, peak tariff" },
  ];
  $("status").replaceChildren(...metrics.map((m) => {
    const d = el("div", `metric${m.attention ? " attention" : ""}`);
    const label = el("div", "metric-label");
    if (m.attention) label.append(el("span", "dot"));
    label.append(document.createTextNode(m.label));
    d.append(label, el("div", "metric-value", m.value), el("div", "metric-note", m.note));
    if (m.attention) d.setAttribute("aria-label", `${m.label} ${m.value}, needs action`);
    return d;
  }));
}

function renderFilter() {
  const all = state.overview?.insights || [];
  $("insights-count").textContent = all.length;
  const opts = ["All", ...SEVERITIES];
  $("severity-filter").replaceChildren(...opts.map((o) => {
    const n = o === "All" ? all.length : all.filter((i) => i.severity === o).length;
    const b = el("button", null, `${o} ${n}`);
    b.type = "button";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(o === state.severity));
    b.disabled = n === 0;
    b.tabIndex = o === state.severity ? 0 : -1;
    b.onclick = () => {
      state.severity = o;
      renderFilter();
      renderInsights();
      $("severity-filter").querySelector('[aria-checked="true"]')?.focus();
    };
    return b;
  }));
}

function renderInsights() {
  const all = state.overview?.insights || [];
  if (!all.length) {
    const e = el("div", "empty");
    e.append(el("p", null, "No insights raised today."), el("p", null, "The proactive insights job runs at 5:15am Brisbane time. Run `./seqwater-demo refresh` to raise them now."));
    $("insights").replaceChildren(e);
    return;
  }
  const out = [];
  for (const sev of SEVERITIES) {
    if (state.severity !== "All" && state.severity !== sev) continue;
    const items = all.filter((i) => i.severity === sev);
    if (!items.length) continue;
    const g = el("h3", "group-title", sev);
    g.append(el("span", null, `· ${SEV_GROUP[sev]}`));
    const list = el("ol", "insight-list");
    for (const i of items) list.append(insightRow(i));
    out.push(g, list);
  }
  $("insights").replaceChildren(...out);
}

function insightRow(i) {
  const li = el("li", "insight");
  const iconName = SITE_ICON[i.site_type];
  if (iconName) {
    const img = el("img", "insight-icon");
    img.src = `/cc-assets/img/icon-${iconName}.webp`;
    img.alt = "";
    img.loading = "lazy";
    li.append(img);
  } else li.append(el("span", "insight-icon"));
  const body = el("div", "insight-body");
  li.dataset.rank = i.rank;
  if (state.activeInsight === i.rank) li.setAttribute("aria-current", "true");
  const top = el("div", "insight-top");
  top.append(sevBadge(i.severity), el("span", null, i.domain));
  const foot = el("div", "insight-foot");
  const who = el("span");
  who.append(document.createTextNode(i.owner_role || ""));
  const impact = money(i.impact_aud);
  if (impact) {
    who.append(document.createTextNode(" · "));
    who.append(el("b", null, `${impact}${i.domain === "Energy" ? " a year" : ""}`));
  }
  const btn = el("button", "btn btn-secondary btn-sm", "Investigate");
  btn.type = "button";
  btn.setAttribute("aria-label", `Investigate: ${i.headline}`);
  btn.onclick = () => {
    state.activeInsight = i.rank;
    renderInsights();
    ask(`Investigate this morning's insight: "${i.headline}". What is driving it, what is the impact, and what should we do now?`);
  };
  const btns = el("div", "insight-buttons");
  if (TWIN_SITES.has(i.site_id)) {
    const tw = el("button", "btn btn-secondary btn-sm", "View in twin");
    tw.type = "button";
    tw.setAttribute("aria-label", `View in the Baroon Pocket twin: ${i.headline}`);
    tw.onclick = () => showView("twin");
    btns.append(tw);
  }
  btns.append(btn);
  foot.append(who, btns);
  body.append(top, el("h4", null, i.headline), el("p", "insight-detail", i.detail), foot);
  li.append(body);
  return li;
}

function renderActions(actions) {
  $("actions-count").textContent = actions?.length || "";
  if (!actions?.length) {
    const e = el("div", "empty");
    e.append(
      el("p", null, "No actions yet."),
      el("p", null, "Ask the agent to raise a work order, notify the regulator or brief a retailer. Nothing happens until you approve it."),
    );
    $("actions").replaceChildren(e);
    return;
  }
  const list = el("ol", "action-list");
  for (const a of actions) {
    const li = el("li", "action");
    const meta = el("p", "action-meta");
    meta.append(document.createTextNode(`${ACTION_LABEL[a.action_type] || a.action_type} `));
    meta.append(el("code", null, a.reference_id || ""));
    meta.append(document.createTextNode(` · approved by ${a.requested_by || "unknown"} · ${bne(a.created_at, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}`));
    li.append(icon("i-check"), el("p", "action-title", a.title || ""), meta);
    list.append(li);
  }
  $("actions").replaceChildren(list);
}

function showTab(which) {
  const ins = which === "insights";
  $("tab-insights").setAttribute("aria-selected", String(ins));
  $("tab-actions").setAttribute("aria-selected", String(!ins));
  $("tab-insights").tabIndex = ins ? 0 : -1;
  $("tab-actions").tabIndex = ins ? -1 : 0;
  $("insights-panel").hidden = !ins;
  $("actions-panel").hidden = ins;
}

let toastTimer;
function toast(message) {
  const t = $("toast");
  const view = el("button", null, "View actions");
  view.type = "button";
  view.onclick = () => { showTab("actions"); t.hidden = true; };
  t.replaceChildren(icon("i-check"), el("span", null, message), view);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 8000);
}

// ------------------------------------------------------------------ chat
function log() { return $("chat-log"); }
function scrollChat() { log().scrollTop = log().scrollHeight; }
function append(node) {
  $("chat-empty")?.remove();
  node.classList.add("enter");
  log().append(node);
  scrollChat();
  return node;
}

function stepsList() {
  if (!state.steps) state.steps = append(el("ol", "steps"));
  return state.steps;
}

function addStep(call) {
  const key = call.id || call.name;
  if (state.toolSteps.has(key)) return; // replayed after an approval pause
  const [running, done] = toolLabel(call);
  const li = el("li", "step running");
  li.dataset.done = done;
  li.append(icon("i-loader"), el("span", null, running));
  stepsList().append(li);
  state.toolSteps.set(key, li);
  scrollChat();
}

function finishStep(id, name) {
  const li = state.toolSteps.get(id) || state.toolSteps.get(name);
  if (!li) return;
  li.className = "step done";
  li.firstChild.replaceWith(icon("i-check"));
  li.lastChild.textContent = li.dataset.done;
}

function waitStep(name) {
  for (const li of state.toolSteps.values()) {
    if (li.classList.contains("running") && ACTIONS[name] && li.lastChild.textContent === toolLabel({ name, args: {} })[0]) {
      li.className = "step waiting";
      li.firstChild.replaceWith(icon("i-pause"));
      li.lastChild.textContent = "Waiting for your approval";
    }
  }
}

function thinking(on) {
  $("thinking")?.remove();
  if (!on) return;
  const li = el("li", "step running");
  li.id = "thinking";
  li.append(icon("i-loader"), el("span", null, state.toolSteps.size ? "Working through the evidence" : "Thinking"));
  stepsList().append(li);
  scrollChat();
}

function onDelta(content) {
  const t = textOf(content);
  if (!t) return;
  thinking(false);
  if (!state.draft) {
    state.steps = null;
    state.draft = { el: append(el("div", "msg-agent md")), text: "" };
  }
  state.draft.text += t;
  state.draft.el.innerHTML = renderMd(state.draft.text);
  scrollChat();
}

function onMessage(m) {
  if (!m) return;
  if (m.type === "ai" || m.type === "AIMessageChunk") {
    const text = textOf(m.content);
    if (state.draft) {
      if (text) state.draft.el.innerHTML = renderMd(text);
      state.draft = null;
    } else if (text) {
      state.steps = null;
      append(el("div", "msg-agent md")).innerHTML = renderMd(text);
    }
    if ((m.tool_calls || []).length) {
      state.steps = null;
      for (const call of m.tool_calls) addStep(call);
      thinking(true);
    }
  } else if (m.type === "tool") {
    finishStep(m.tool_call_id, m.name);
    if (ACTIONS[m.name]) onActionResult(m);
  }
}

function onActionResult(m) {
  let res = {};
  try { res = JSON.parse(textOf(m.content)); } catch {}
  const ref = res.work_order_id || res.reference_id;
  if (state.approvalCard && ref) {
    const line = state.approvalCard.querySelector(".decision span");
    if (line) line.textContent += ` · ${ref}`;
  }
  if (ref) toast(`${ACTIONS[m.name].noun} ${ref} recorded in Unity Catalog`);
  loadOverview(true);
  if (m.name === "request_offtake_change" && twin.api) twin.api.refresh(true);
}

function onInterrupt(ev) {
  thinking(false);
  state.draft = null;
  state.steps = null;
  const reqs = ev?.value?.action_requests || [];
  const spec = ACTIONS[reqs[0]?.name] || { title: "Approve action", button: "Approve", noun: "Action" };
  if (reqs[0]?.name) waitStep(reqs[0].name);
  const card = el("section", "approval");
  card.setAttribute("aria-label", `Approval needed: ${spec.title}`);
  const head = el("div", "approval-head");
  head.append(icon("i-pause"), el("h3", null, `Approval needed: ${spec.title}`));
  card.append(head, el("p", null, "The agent has paused. Nothing is recorded until you decide."));
  for (const r of reqs) {
    const dl = el("dl");
    for (const [k, v] of Object.entries(r.args || {})) {
      const val = typeof v === "string" ? v : JSON.stringify(v);
      dl.append(el("dt", null, FIELD_LABELS[k] || k.replaceAll("_", " ")), el("dd", val.length > 160 ? "long" : null, val));
    }
    card.append(dl);
  }
  const row = el("div", "approval-actions");
  const ok = el("button", "btn btn-primary", spec.button);
  const no = el("button", "btn btn-secondary", "Reject");
  ok.type = no.type = "button";
  const decide = (type) => {
    const who = state.viewer || "you";
    const time = new Date().toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" });
    const done = el("div", `decision${type === "approve" ? "" : " rejected"}`);
    done.append(icon(type === "approve" ? "i-shield" : "i-x"),
      el("span", null, type === "approve" ? `${spec.title}: approved by ${who} at ${time}` : `${spec.title}: rejected by ${who} at ${time}`));
    card.className = "approval decided";
    card.replaceChildren(done);
    for (const li of state.toolSteps.values()) {
      if (li.classList.contains("waiting")) {
        li.className = type === "approve" ? "step running" : "step done";
        li.firstChild.replaceWith(icon(type === "approve" ? "i-loader" : "i-x"));
        li.lastChild.textContent = type === "approve" ? "Recording the approved action" : "Action rejected";
      }
    }
    state.approvalCard = card;
    setPending(false);
    const decisions = reqs.map(() => (type === "approve" ? { type: "approve" } : { type: "reject", message: "Rejected by the approver in the Command Centre." }));
    invoke({ resume: { decisions } });
  };
  ok.onclick = () => decide("approve");
  no.onclick = () => decide("reject");
  row.append(ok, no);
  card.append(row);
  append(card);
  setPending(true);
  ok.focus({ preventScroll: true });
}

function setPending(p) {
  state.pending = p;
  $("prompt").disabled = p;
  $("prompt").placeholder = p ? "Approve or reject the pending action to continue" : "Ask the Operations Agent, for example: why is Landers Shute flagged?";
  updateSend();
}
function setBusy(b) { state.busy = b; updateSend(); }
function updateSend() {
  $("send").disabled = state.busy || state.pending;
  $("send").textContent = state.busy ? "Working" : "Ask";
}

function handle(ev) {
  if (!ev) return;
  if (ev.type === "delta") onDelta(ev.content);
  else if (ev.type === "message") onMessage(ev.message);
  else if (ev.type === "interrupt") onInterrupt(ev);
  else if (ev.type === "run.failed") throw new Error("the agent run failed. Check the app logs with `agentbricks deployments logs`.");
  else if (ev.error) throw new Error(typeof ev.error === "string" ? ev.error : JSON.stringify(ev.error));
}

function parseFrame(frame) {
  const data = frame.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
  if (!data || data === "[DONE]") return null;
  try { return JSON.parse(data); } catch { return null; }
}

async function invoke(input) {
  setBusy(true);
  thinking(true);
  const body = { id: uuid(), session_id: state.sessionId, input: { ...input, actor: state.viewer || "presenter" }, stream: true };
  try {
    const r = await fetch("/api/invocations", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Routing-Key": state.sessionId },
      body: JSON.stringify(body),
    });
    if (!r.ok || !r.body) throw new Error(`${r.status} ${await r.text()}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      buf += dec.decode(value || new Uint8Array(), { stream: !done });
      const frames = buf.split("\n\n");
      buf = frames.pop() || "";
      for (const f of frames) handle(parseFrame(f));
      if (done) break;
    }
    if (buf.trim()) handle(parseFrame(buf));
  } catch (e) {
    append(el("div", "msg-error", `The agent couldn't answer: ${e.message} Try again, or start a new conversation.`));
  } finally {
    thinking(false);
    state.draft = null;
    state.steps = null;
    setBusy(false);
  }
}

function ask(text) {
  const t = (text || "").trim();
  if (!t || state.busy || state.pending) return;
  append(el("div", "msg-user", t));
  state.steps = null;
  state.toolSteps.clear();
  $("prompt").value = "";
  invoke({ messages: [{ role: "user", content: t }] });
}

function emptyChat() {
  const box = el("div", "chat-empty");
  box.id = "chat-empty";
  box.append(el("p", null, "Ask about anything across the Water Grid, or choose Investigate on an insight. Try:"));
  const list = el("ul", "suggestions");
  for (const s of SUGGESTIONS) {
    const li = el("li");
    const b = el("button", "suggestion");
    b.type = "button";
    b.append(el("span", null, s), icon("i-arrow"));
    b.onclick = () => ask(s);
    li.append(b);
    list.append(li);
  }
  box.append(list);
  log().replaceChildren(box);
}

function newChat() {
  state.sessionId = uuid();
  state.draft = state.steps = state.approvalCard = null;
  state.toolSteps.clear();
  state.activeInsight = null;
  setPending(false);
  emptyChat();
  renderInsights();
}

// ------------------------------------------------------------------ views (Command Centre / Baroon Pocket twin)
const twin = { api: null, loading: null };
async function showView(view) {
  const isTwin = view === "twin";
  document.querySelectorAll(".view").forEach((b) => (b.dataset.view === view ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  document.querySelector(".shell").classList.toggle("twin-mode", isTwin);
  document.querySelector(".pane-insights").hidden = isTwin;
  $("pane-twin").hidden = !isTwin;
  if (!isTwin || twin.api || twin.loading) return;
  twin.loading = import("/cc-assets/twin.js?v=4")
    .then((mod) => mod.mountTwin($("pane-twin"), { onAsk: (q) => ask(q) }))
    .then((api) => { twin.api = api; })
    .catch((e) => {
      const box = el("div", "error-box");
      box.append(el("p", null, `Couldn't load the twin: ${e.message}`), el("p", "meta", "Check the reservoir tables exist (run ./seqwater-demo refresh) and that the browser supports WebGL."));
      document.querySelector(".twin-stage").replaceChildren(box);
    });
}
document.querySelectorAll(".view").forEach((b) => (b.onclick = () => showView(b.dataset.view)));

// ------------------------------------------------------------------ briefing drawer
function openBrief() {
  const b = state.overview?.briefing;
  $("brief-body").innerHTML = b?.briefing_markdown
    ? renderMd(b.briefing_markdown)
    : "<p>No briefing yet. The proactive insights job writes it at 5:15am Brisbane time.</p>";
  $("brief-dialog").showModal();
}

// ------------------------------------------------------------------ boot
$("composer").addEventListener("submit", (e) => { e.preventDefault(); ask($("prompt").value); });
$("prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask($("prompt").value); }
});
$("new-chat").onclick = newChat;
$("open-brief").onclick = openBrief;
$("close-brief").onclick = () => $("brief-dialog").close();
$("brief-dialog").addEventListener("click", (e) => { if (e.target === $("brief-dialog")) $("brief-dialog").close(); });
$("tab-insights").onclick = () => showTab("insights");
$("tab-actions").onclick = () => showTab("actions");
// arrow keys move between tabs and between severity options (WAI-ARIA tabs / radio group)
function arrowNav(container, selector, activate) {
  container.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const items = [...container.querySelectorAll(selector)].filter((x) => !x.disabled);
    const i = items.indexOf(document.activeElement);
    if (i < 0) return;
    const next = items[(i + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length];
    next.focus();
    activate(next);
    e.preventDefault();
  });
}
arrowNav(document.querySelector(".tabs"), ".tab", (t) => showTab(t.id === "tab-actions" ? "actions" : "insights"));
arrowNav($("severity-filter"), "button", (b) => b.click());

(async () => {
  showTab("insights");
  emptyChat();
  skeleton();
  try {
    const r = await fetch(`/api/ui/config?session_id=${encodeURIComponent(state.sessionId)}`, { credentials: "same-origin" });
    const c = await r.json();
    state.viewer = c.viewer && c.viewer !== "Local developer" ? c.viewer : null;
    $("viewer").textContent = state.viewer || "";
  } catch {}
  await loadOverview();
})();
