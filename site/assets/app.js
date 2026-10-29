/* Replay recorded kill-switch runs. No model is called unless Run live is used. */

const CX = 170;
const CY = 156;
const R = 108;

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const params = new URLSearchParams(location.search);
const atParam = params.get("at");

const els = {
  list: document.getElementById("scenario-list"),
  title: document.getElementById("task-title"),
  summary: document.getElementById("task-summary"),
  instruction: document.getElementById("task-instruction"),
  kicker: document.getElementById("task-kicker"),
  gauge: document.getElementById("gauge"),
  spent: document.getElementById("spent-value"),
  proj: document.getElementById("proj-value"),
  next: document.getElementById("next-call"),
  lamps: document.getElementById("lamps"),
  depth: document.getElementById("depth-value"),
  depthUnit: document.getElementById("depth-unit"),
  repeat: document.getElementById("repeat-line"),
  tiers: document.getElementById("tiers"),
  blurb: document.getElementById("tier-blurb"),
  banner: document.getElementById("banner"),
  trace: document.getElementById("trace"),
  answer: document.getElementById("answer"),
  ledgerBody: document.querySelector("#ledger tbody"),
  frameLabel: document.getElementById("frame-label"),
  replay: document.getElementById("replay"),
  scrub: document.getElementById("scrub"),
  live: document.getElementById("live"),
  caption: document.getElementById("caption"),
  cap: document.getElementById("cap-pill"),
  mode: document.getElementById("mode-pill"),
};

let indexDoc = null;
let runs = {};
let current = null;
let timer = null;
let honorAt = true;
let liveNote = false;

function money4(value) {
  return "$" + Number(value).toFixed(4);
}

function money2(value) {
  return "$" + Number(value).toFixed(2);
}

function polar(t) {
  const clamped = Math.min(1, Math.max(0, t));
  const theta = Math.PI * (1 - clamped);
  return [CX + R * Math.cos(theta), CY - R * Math.sin(theta)];
}

function arcPath(t0, t1) {
  if (t1 <= t0) return "";
  const steps = 40;
  let d = "";
  for (let i = 0; i <= steps; i += 1) {
    const t = t0 + ((t1 - t0) * i) / steps;
    const [x, y] = polar(t);
    d += (i === 0 ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1) + " ";
  }
  return d;
}

function initGauge() {
  const ns = "http://www.w3.org/2000/svg";
  const make = (name, attrs) => {
    const node = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  };
  els.gauge.append(
    make("path", { id: "arc-track", d: arcPath(0, 1), fill: "none", stroke: "rgba(243,236,223,0.16)", "stroke-width": "16", "stroke-linecap": "round" }),
    make("path", { id: "arc-proj", d: "", fill: "none", stroke: "#e3925b", "stroke-width": "16", "stroke-linecap": "round", opacity: "0.9" }),
    make("path", { id: "arc-spent", d: "", fill: "none", stroke: "#d6f07a", "stroke-width": "8", "stroke-linecap": "round" }),
  );
  ["soft", "hard"].forEach((id) => {
    els.gauge.append(make("line", { id: "tick-" + id, stroke: "#f3ecdf", "stroke-width": "1.5" }));
    els.gauge.append(make("text", { id: "label-" + id, fill: "#b3a594", "font-size": "11", "font-family": "IBM Plex Mono, monospace" }));
  });
}

function placeTick(id, t, text, anchor, fill) {
  const clamped = Math.min(1, Math.max(0, t));
  const theta = Math.PI * (1 - clamped);
  const x = CX + R * Math.cos(theta);
  const y = CY - R * Math.sin(theta);
  const x2 = CX + (R + 10) * Math.cos(theta);
  const y2 = CY - (R + 10) * Math.sin(theta);
  const line = document.getElementById("tick-" + id);
  line.setAttribute("x1", x.toFixed(1));
  line.setAttribute("y1", y.toFixed(1));
  line.setAttribute("x2", x2.toFixed(1));
  line.setAttribute("y2", y2.toFixed(1));
  const label = document.getElementById("label-" + id);
  label.textContent = text;
  label.setAttribute("fill", fill || "#b3a594");
  label.setAttribute("text-anchor", anchor);
  label.setAttribute("x", x2.toFixed(1));
  label.setAttribute("y", (CY + 18).toFixed(1));
}

function stop() {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
}

function settle() {
  document.body.dataset.settled = "1";
}

function show(index) {
  const frames = current.snapshots;
  const i = Math.max(0, Math.min(frames.length - 1, index));
  paint(frames[i]);
  els.scrub.value = String(i);
}

function play(from) {
  stop();
  liveNote = false;
  document.body.dataset.settled = "0";
  const frames = current.snapshots;
  let i = from;
  const tick = () => {
    show(i);
    i += 1;
    if (i < frames.length) {
      timer = setTimeout(tick, 780);
    } else {
      timer = null;
      settle();
    }
  };
  tick();
}

function paint(frame) {
  const hard = Number(frame.hard_budget_usd);
  const soft = Number(frame.soft_budget_usd);
  const spent = Number(frame.spent_usd);
  const projected = Number(frame.projected_usd);
  const spentT = hard > 0 ? spent / hard : 0;
  const projT = hard > 0 ? projected / hard : 0;
  document.getElementById("arc-spent").setAttribute("d", arcPath(0, Math.min(spentT, 1)));
  document.getElementById("arc-proj").setAttribute("d", arcPath(0, Math.min(projT, 1)));
  document.getElementById("arc-spent").setAttribute("stroke", spentT > 1 ? "#ff6a4a" : "#d6f07a");
  document.getElementById("arc-proj").setAttribute("stroke", projT > 1 ? "#ff6a4a" : "#e3925b");
  placeTick("soft", soft / hard, "soft " + money2(frame.soft_budget_usd), "middle", "#e6b15a");
  placeTick("hard", 1, projT > 1 ? "over cap" : "hard " + money2(frame.hard_budget_usd), "end", projT > 1 ? "#ff6a4a" : "#b3a594");

  els.spent.textContent = money4(frame.spent_usd);
  if (frame.status === "completed") {
    els.proj.textContent = "finished under soft " + money2(frame.soft_budget_usd);
    els.proj.classList.remove("over");
  } else if (projected > hard) {
    els.proj.textContent = "projected " + money4(frame.projected_usd);
    els.proj.classList.add("over");
  } else {
    els.proj.textContent = "projected " + money4(frame.projected_usd);
    els.proj.classList.remove("over");
  }
  const toks = Number(frame.prompt_tokens_next).toLocaleString("en-US");
  els.next.textContent = "next prompt " + toks + " tok · est. " + frame.completion_tokens_est + " out";

  els.depth.textContent = String(frame.depth);
  els.depthUnit.textContent = "/ " + frame.max_depth;
  const lamps = els.lamps.querySelectorAll(".lamp");
  lamps.forEach((lamp, i) => {
    const repeatTrip = frame.halt_code === "repeated_tool_call" && i === frame.depth - 1;
    const depthTrip = frame.halt_code === "loop_depth" && i === frame.max_depth - 1;
    lamp.classList.toggle("tripped", repeatTrip || depthTrip);
    lamp.classList.toggle("on", i < frame.depth && !repeatTrip && !depthTrip);
  });
  els.repeat.textContent = "same call " + frame.repeat_count + " / " + frame.repeat_limit;
  els.repeat.title = frame.repeat_label || "No repeated tool call yet";

  els.tiers.querySelectorAll(".tier").forEach((node) => {
    const view = frame.tiers.find((t) => t.tier === node.dataset.tier);
    if (!view) return;
    node.dataset.state = view.state;
    node.querySelector(".flag").textContent = flag(view.state);
  });
  const active = frame.tiers.find((view) => view.state === "active");
  const failed = frame.tiers.find((view) => view.state === "failed");
  els.blurb.textContent = active ? active.blurb : failed ? failed.blurb : "";

  paintBanner(frame);
  paintTrace(frame);
  paintLedger(frame);
  els.frameLabel.textContent = (frame.index + 1) + " / " + current.snapshots.length;
  document.body.dataset.status = frame.status;
  document.body.dataset.frame = String(frame.index);
  if (frame.final_text) {
    els.answer.hidden = false;
    els.answer.textContent = frame.final_text;
  } else {
    els.answer.hidden = true;
    els.answer.textContent = "";
  }
}

function flag(state) {
  if (state === "active") return "live";
  if (state === "stood_down") return "down";
  if (state === "failed") return "out";
  return "idle";
}

function paintBanner(frame) {
  const banner = els.banner;
  if (frame.status === "halted") {
    banner.dataset.tone = "halted";
    const code = (frame.halt_code || "halt").replaceAll("_", " ");
    banner.innerHTML = "<p class='stamp'>Breaker open · " + code + "</p><h3>" + escapeHtml(frame.title) + "</h3><p>" + escapeHtml(frame.halt_message || frame.detail) + "</p>";
    return;
  }
  if (frame.status === "completed") {
    banner.dataset.tone = "completed";
    banner.innerHTML = "<p class='stamp'>Breaker closed</p><h3>Task finished</h3><p>" + escapeHtml(frame.detail) + "</p>";
    return;
  }
  banner.dataset.tone = "running";
  banner.innerHTML = "<p class='stamp'>Breaker closed · loop running</p><h3>" + escapeHtml(frame.title) + "</h3><p>" + escapeHtml(frame.detail) + "</p>";
}

function paintTrace(frame) {
  els.trace.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.index) === frame.index);
  });
}

function paintLedger(frame) {
  const body = els.ledgerBody;
  body.replaceChildren();
  if (!frame.rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td class='empty' colspan='7'>No model call has been billed yet.</td>";
    body.append(tr);
    return;
  }
  frame.rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = [
      "<td class='num'>" + row.depth + "</td>",
      "<td>" + escapeHtml(row.tier) + "</td>",
      "<td class='num'>" + row.prompt_tokens.toLocaleString("en-US") + "</td>",
      "<td class='num'>" + row.completion_tokens.toLocaleString("en-US") + "</td>",
      "<td class='num'>" + money4(row.cost_usd) + "</td>",
      "<td class='num'>" + money4(row.cumulative_usd) + "</td>",
      "<td class='decision'>" + escapeHtml(row.decision) + "</td>",
    ].join("");
    body.append(tr);
  });
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function buildChrome(report) {
  els.title.textContent = report.title;
  els.summary.textContent = report.summary;
  els.instruction.textContent = report.instruction;
  els.kicker.textContent = report.id;
  const maxDepth = report.max_loop_depth;
  els.lamps.replaceChildren();
  for (let i = 0; i < maxDepth; i += 1) {
    const lamp = document.createElement("span");
    lamp.className = "lamp";
    lamp.title = "Depth " + (i + 1);
    els.lamps.append(lamp);
  }
  els.tiers.replaceChildren();
  report.snapshots[0].tiers.forEach((view) => {
    const node = document.createElement("div");
    node.className = "tier";
    node.dataset.tier = view.tier;
    node.dataset.state = view.state;
    node.innerHTML =
      "<div><div class='name'>" + escapeHtml(view.display_name) + "</div>" +
      "<div class='model'>" + escapeHtml(view.model_id) + "</div>" +
      "<div class='rate'>" + money2(view.input_per_million_usd) + " in · " + money2(view.output_per_million_usd) + " out / 1M</div></div>" +
      "<div class='flag'>" + flag(view.state) + "</div>";
    els.tiers.append(node);
  });
  els.trace.replaceChildren();
  report.snapshots.forEach((frame) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.index = String(frame.index);
    button.innerHTML =
      "<span class='kicker'>" + escapeHtml(frame.kicker) + "</span>" +
      "<strong>" + escapeHtml(frame.title) + "</strong>" +
      "<span class='detail'>" + escapeHtml(frame.detail) + "</span>";
    button.addEventListener("click", () => {
      stop();
      settle();
      show(frame.index);
    });
    li.append(button);
    els.trace.append(li);
  });
  els.scrub.max = String(report.snapshots.length - 1);
  document.body.dataset.scenario = report.id;
  els.list.querySelectorAll(".scenario").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.id === report.id ? "true" : "false");
  });
}

function openScenario(id, user) {
  const report = runs[id];
  if (!report) return;
  stop();
  current = report;
  if (location.hash !== "#" + id) {
    history.replaceState(null, "", "#" + id + location.search);
  }
  buildChrome(report);
  const last = report.snapshots.length - 1;
  if (!user && honorAt && atParam === "end") {
    show(last);
    settle();
  } else if (!user && honorAt && atParam !== null && atParam !== "") {
    show(Number(atParam));
    settle();
  } else if (reduced) {
    show(last);
    settle();
  } else {
    play(0);
  }
  honorAt = false;
  if (!liveNote) {
    els.caption.textContent = "Playing a recorded run. This page does not call a model.";
    els.mode.textContent = "Recorded run";
  }
}

function renderNav() {
  els.cap.textContent = "Hard cap " + money2(indexDoc.hard_budget_usd);
  els.list.replaceChildren();
  indexDoc.scenarios.forEach((item, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scenario";
    button.dataset.id = item.id;
    button.setAttribute("aria-pressed", "false");
    const end = item.status === "completed"
      ? "<span class='pill-end'>ends completed</span>"
      : "<span class='pill-halt'>ends halted · " + escapeHtml((item.halt_code || "").replaceAll("_", " ")) + "</span>";
    button.innerHTML =
      "<span class='idx'>" + String(i + 1).padStart(2, "0") + "</span>" +
      "<span><strong>" + escapeHtml(item.title) + "</strong><em>" + escapeHtml(item.summary) + "</em><em>" + end + "</em></span>";
    button.addEventListener("click", () => openScenario(item.id, true));
    els.list.append(button);
  });
}

async function probeLive() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) return;
    const health = await response.json();
    if (!health.ok) return;
    els.live.hidden = false;
    document.body.dataset.live = "1";
  } catch (err) {
    els.live.hidden = true;
  }
}

async function runLive() {
  if (!current) return;
  els.live.disabled = true;
  els.caption.textContent = "Running on the local engine…";
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario: current.id }),
    });
    if (!response.ok) throw new Error("run failed");
    const report = await response.json();
    runs[current.id] = report;
    liveNote = true;
    els.mode.textContent = "Live engine";
    els.caption.textContent = "Ran just now on the local engine. Prices are still the example table.";
    stop();
    current = report;
    buildChrome(report);
    if (reduced) {
      show(report.snapshots.length - 1);
      settle();
    } else {
      play(0);
    }
  } catch (err) {
    els.caption.textContent = "The local engine did not answer. The recorded run is still loaded.";
  } finally {
    els.live.disabled = false;
  }
}

els.replay.addEventListener("click", () => {
  liveNote = false;
  if (current) play(0);
});
els.scrub.addEventListener("input", () => {
  stop();
  settle();
  show(Number(els.scrub.value));
});
els.live.addEventListener("click", runLive);

document.addEventListener("keydown", (event) => {
  if (!indexDoc || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === " ") {
    event.preventDefault();
    if (current) play(0);
  }
  const n = Number(event.key);
  if (n >= 1 && n <= indexDoc.scenarios.length) {
    openScenario(indexDoc.scenarios[n - 1].id, true);
  }
});

async function boot() {
  initGauge();
  try {
    indexDoc = await fetch("data/index.json").then((r) => r.json());
    await Promise.all(indexDoc.scenarios.map(async (item) => {
      runs[item.id] = await fetch("data/" + item.file).then((r) => r.json());
    }));
  } catch (err) {
    els.title.textContent = "Could not load site/data";
    els.summary.textContent = "Serve this folder over HTTP (make run) so the recorded JSON can load.";
    document.body.dataset.ready = "1";
    document.body.dataset.settled = "1";
    return;
  }
  renderNav();
  const wanted = params.get("scenario") || location.hash.replace("#", "") || indexDoc.scenarios[0].id;
  const id = runs[wanted] ? wanted : indexDoc.scenarios[0].id;
  openScenario(id, false);
  document.body.dataset.ready = "1";
  probeLive();
}

boot();
