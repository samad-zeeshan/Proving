// Replays recorded simulations from data/*.json. Nothing here calls an agent or a model.
"use strict";

const state = { index: null, client: null, data: null, a: null, b: null, view: "run", timers: [] };
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (s) => document.querySelector(s);

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined) n.append(kid.nodeType ? kid : String(kid));
  return n;
}

const pct = (x) => (x === null || x === undefined ? "n/a" : `${(x * 100).toFixed(1)}%`);
const num = (x, d = 2) => (x === null || x === undefined ? "n/a" : Number(x).toFixed(d));
const nice = (v) => v.replace("|", ", ").replace("noise@", "noise ").replace("asr@", "audio ");

function stopTimers() {
  state.timers.forEach(clearTimeout);
  state.timers = [];
}

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// ---------------------------------------------------------------- controls

async function boot() {
  state.index = await getJSON("data/index.json");
  const group = $("#clients");
  state.index.clients.forEach((c) => {
    group.append(el("button", { type: "button", role: "radio", "aria-checked": "false", "data-client": c.client,
      onclick: () => selectClient(c.client), text: c.label }));
  });
  document.querySelectorAll(".actions button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
  $("#version-a").addEventListener("change", (e) => { state.a = e.target.value; notes(); show(state.view); });
  $("#version-b").addEventListener("change", (e) => { state.b = e.target.value; notes(); show(state.view); });
  $("#drawer-close").addEventListener("click", () => $("#drawer").close());
  await selectClient(state.index.clients[0].client);
}

async function selectClient(id) {
  stopTimers();
  state.client = id;
  document.querySelectorAll("#clients button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.client === id)));
  state.data = await getJSON(`data/${id}.json`);
  const d = state.data;
  $("#client-blurb").textContent = d.blurb;
  for (const [sel, pickDefault] of [["#version-a", d.comparison.baseline], ["#version-b", d.comparison.candidate]]) {
    const s = $(sel);
    s.replaceChildren(...d.versions.map((v) => el("option", { value: v, text: nice(v), selected: v === pickDefault })));
  }
  state.a = d.comparison.baseline;
  state.b = d.comparison.candidate;
  notes();
  show(state.view);
}

function notes() {
  $("#note-a").textContent = state.data.notes[state.a] || "";
  $("#note-b").textContent = state.data.notes[state.b] || "";
}

function show(view) {
  stopTimers();
  state.view = view;
  document.querySelectorAll(".actions button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  const stage = $("#stage");
  stage.replaceChildren();
  ({ run: renderRun, report: renderReport, regression: renderRegression, attacks: renderAttacks })[view](stage);
}

// ---------------------------------------------------------------- tiles and transcripts

function outcomeClass(t) {
  if (t.missing) return "missing";
  if (t.hazards && t.hazards.length) return "hazard";
  if (t.end === "patience") return "gaveup";
  return t.success ? "ok" : "fail";
}

function outcomeText(t) {
  if (t.missing) return "not run for this version";
  const bits = [t.success ? "goal met" : "goal not met"];
  if (t.end === "patience") bits.push("the customer gave up");
  if (t.hazards.length) bits.push(`hazard: ${t.hazards.join(", ").replaceAll("_", " ")}`);
  return bits.join(", ");
}

function openTranscript(title, meta, turns, calls) {
  $("#drawer-title").textContent = title;
  $("#drawer-meta").textContent = meta;
  const body = $("#drawer-body");
  body.replaceChildren();
  turns.forEach(([c, a]) => {
    if (c) body.append(el("li", { class: "c" }, el("span", { class: "who", text: "Customer" }), c));
    if (a) body.append(el("li", { class: "a" }, el("span", { class: "who", text: "Agent" }), a));
  });
  if (calls && calls.length) {
    const planted = calls.filter((x) => x.phase === "steered");
    if (planted.length) {
      body.append(el("li", { class: "c" }, el("span", { class: "who", text: "Planted calls that reached the server" }),
        planted.map((x) => `${x.tool} (${x.ok ? "ran" : "refused"})`).join(", ")));
    }
  }
  $("#drawer").showModal();
}

// ---------------------------------------------------------------- run view

function renderRun(stage) {
  const d = state.data;
  const wrap = el("div", { class: "runs" });
  const panels = [state.a, state.b].map((v, side) => {
    const tiles = d.grid[v];
    const grid = el("div", { class: "grid", role: "list", "aria-label": `Customers for ${nice(v)}` });
    const counts = el("div", { class: "counts" });
    const tally = { done: 0, ok: 0, hazard: 0, gaveup: 0 };
    const paint = () => {
      counts.replaceChildren(
        el("span", {}, el("b", { text: tally.done }), ` of ${tiles.length} done`),
        el("span", {}, el("b", { text: tally.ok }), " goal met"),
        el("span", {}, el("b", { text: tally.hazard }), " hazard"),
        el("span", {}, el("b", { text: tally.gaveup }), " gave up"));
    };
    tiles.forEach((t, i) => {
      const btn = el("button", { type: "button", class: `tile${t.adversarial ? " adv" : ""}`, role: "listitem",
        "aria-label": `${t.id}: running`, onclick: () => !t.missing && openTranscript(t.id,
          `${nice(v)}. ${t.language}. ${outcomeText(t)}.`, t.turns, t.calls) });
      grid.append(btn);
      const finish = () => {
        const cls = outcomeClass(t);
        btn.className = `tile ${cls}${t.adversarial ? " adv" : ""}`;
        btn.setAttribute("aria-label", `${t.id}: ${outcomeText(t)}`);
        if (!t.missing) {
          tally.done += 1;
          if (t.success) tally.ok += 1;
          if (cls === "hazard") tally.hazard += 1;
          if (t.end === "patience") tally.gaveup += 1;
        }
        paint();
      };
      if (reduced || t.missing) { finish(); return; }
      // Spread the starts so the grid fills like a batch of calls, then step through each call's turns.
      const start = ((i * 389 + side * 131) % 1000) * 3.2;
      const n = Math.max(1, t.turns.length);
      state.timers.push(setTimeout(() => btn.classList.add("running"), start));
      for (let k = 1; k <= n; k += 1) {
        state.timers.push(setTimeout(() => btn.style.setProperty("--p", `${(100 * k) / n}%`), start + k * 260));
      }
      state.timers.push(setTimeout(finish, start + n * 260 + 120));
    });
    paint();
    return el("div", { class: "panel runpanel" },
      el("h3", { text: `${side ? "Candidate" : "Current"}: ${nice(v)}` }),
      el("p", { class: "sub", text: d.notes[v] }), grid, counts);
  });
  wrap.append(...panels);
  stage.append(wrap, el("div", { class: "legend" },
    el("span", {}, el("i", { style: "background:var(--ok)" }), "goal met"),
    el("span", {}, el("i", { style: "background:var(--fail)" }), "goal not met"),
    el("span", {}, el("i", { style: "background:var(--gaveup)" }), "customer gave up"),
    el("span", {}, el("i", { style: "background:var(--hazard)" }), "hazard"),
    el("span", { text: "Dot: adversarial persona. Click a square to read the call." })));
}

// ---------------------------------------------------------------- report view

function ciBar(h) {
  const [lo, hi] = h.ci;
  const minE = h.min_effect;
  const left = Math.min(lo, 0, -minE);
  const right = Math.max(hi, minE, 0);
  const span = right - left || 1;
  const pos = (x) => `${((x - left) / span) * 100}%`;
  return el("div", {},
    el("div", { class: "ci", role: "img", "aria-label": `Improvement from ${num(lo, 3)} to ${num(hi, 3)}` },
      el("div", { class: "ci__axis" }),
      el("div", { class: "ci__zero", style: `left:${pos(0)}` }),
      el("div", { class: "ci__min", style: `left:${pos(minE)}` }),
      el("div", { class: "ci__bar", style: `left:${pos(lo)};width:calc(${pos(hi)} - ${pos(lo)})` })),
    el("div", { class: "ci__labels" }, el("span", { text: num(left, 2) }), el("span", { text: num(right, 2) })),
    el("p", { class: "field__note", text: `Bar: the interval. Grey line: no change. Amber line: the smallest improvement worth shipping for (${minE}).` }));
}

function renderReport(stage) {
  const d = state.data;
  const r = d.report;
  const same = state.a === d.comparison.baseline && state.b === d.comparison.candidate;
  if (!same) {
    stage.append(el("div", { class: "panel summary" },
      el("p", { text: `The report is written for ${nice(d.comparison.baseline)} against ${nice(d.comparison.candidate)}, the change this agent was screened for. For the pair you picked, these are the counts from the customers on this page.` }),
      pairTable(d.grid[state.a], d.grid[state.b])));
    return;
  }
  const word = r.verdict === "needs more evidence" ? "more" : r.verdict;
  const bar = r.evidence_bar;
  const b = r.baseline_summary;
  const c = r.candidate_summary;
  const perRun = (x, s) => (s.valid ? x / s.valid : 0);
  const comps = ["base_prompt", "injected_context", "inference", "miss_penalty", "accumulation"];
  const maxTok = Math.max(1, ...comps.map((k) => perRun(c.cost[k], c)));
  stage.append(el("div", { class: "panel report" },
    el("div", { class: "verdict" }, el("span", { class: `verdict__word ${word}`, text: r.verdict }),
      el("span", { class: "verdict__line", text: r.verdict_line })),
    el("div", { class: "cols" },
      ...r.hypotheses.map((h) => el("div", { class: "card" },
        el("h4", { text: `Hypothesis: ${h.verdict}` }), el("p", { text: h.claim }),
        el("p", { class: "num", text: `${h.metric}: ${num(h.baseline_mean, 3)} to ${num(h.candidate_mean, 3)} over ${h.n} scenarios` }),
        ciBar(h),
        el("p", { class: "num", text: `improvement ${num(h.improvement, 3)}, ${Math.round(h.level * 100)}% interval ${num(h.ci[0], 3)} to ${num(h.ci[1], 3)}` }))),
      el("div", { class: "card" }, el("h4", { text: "Evidence bar" }),
        el("p", { text: `Autonomy ${r.deployment.autonomy}: ${r.deployment.autonomy_why}` }),
        el("p", { text: `Consequence ${r.deployment.consequence}: ${r.deployment.consequence_why}` }),
        el("p", { text: `So the bar is ${bar.tier}: ${Math.round(bar.confidence * 100)}% confidence, at least ${bar.min_scenarios} scenarios, hazards in at most ${pct(bar.max_hazard_rate)} of calls, task success may not fall more than ${pct(bar.success_margin)}.` }))),
    el("div", { class: "cols" },
      el("div", { class: "card" }, el("h4", { text: "Gates" }),
        el("ul", { class: "gates" }, ...r.gates.map((g) => el("li", {},
          el("span", { class: `badge ${g.outcome}`, text: g.outcome }), el("span", { text: `${g.gate}. ${g.detail}` }))))),
      el("div", { class: "card" }, el("h4", { text: "Numbers" }),
        el("div", { class: "kv" },
          el("span", { class: "h", text: "" }), el("span", { class: "h", text: nice(r.baseline) }), el("span", { class: "h", text: nice(r.candidate) }),
          "task success", el("span", { class: "num", text: pct(b.success_rate) }), el("span", { class: "num", text: pct(c.success_rate) }),
          "calls with a hazard", el("span", { class: "num", text: `${b.hazard_runs} of ${b.valid}` }), el("span", { class: "num", text: `${c.hazard_runs} of ${c.valid}` }),
          "customer gave up", el("span", { class: "num", text: b.abandoned }), el("span", { class: "num", text: c.abandoned }),
          "turn latency p50", el("span", { class: "num", text: `${num(b.latency_ms.p50, 1)} ms` }), el("span", { class: "num", text: `${num(c.latency_ms.p50, 1)} ms` }),
          "model tokens per call", el("span", { class: "num", text: num(b.tokens.per_run, 0) }), el("span", { class: "num", text: num(c.tokens.per_run, 0) })),
        c.tokens.total ? el("div", { class: "bars", style: "margin-top:12px" },
          el("p", { text: `Where the candidate's tokens go, per call:` }),
          ...comps.map((k) => el("div", { class: "bar" }, el("span", { text: k.replace("_", " ") }),
            el("span", { style: `width:${(perRun(c.cost[k], c) / maxTok) * 100}%` }),
            el("span", { class: "num", text: num(perRun(c.cost[k], c), 0) })))) : el("p", { style: "margin-top:10px", text: "Neither version calls a model, so there is no token cost to split." })))));
}

function pairTable(ta, tb) {
  const sum = (ts) => {
    const run = ts.filter((t) => !t.missing);
    return { n: run.length, ok: run.filter((t) => t.success).length, hz: run.filter((t) => t.hazards.length).length };
  };
  const a = sum(ta);
  const b = sum(tb);
  return el("div", { class: "kv", style: "margin-top:10px" },
    el("span", { class: "h", text: "" }), el("span", { class: "h", text: nice(state.a) }), el("span", { class: "h", text: nice(state.b) }),
    "customers replayed", el("span", { class: "num", text: a.n }), el("span", { class: "num", text: b.n }),
    "goal met", el("span", { class: "num", text: a.ok }), el("span", { class: "num", text: b.ok }),
    "with a hazard", el("span", { class: "num", text: a.hz }), el("span", { class: "num", text: b.hz }));
}

// ---------------------------------------------------------------- regression view

function renderRegression(stage) {
  const reg = state.data.regression;
  if (!reg) {
    stage.append(el("p", { class: "empty", text: "No regression replay was recorded for this agent." }));
    return;
  }
  const c = reg.case;
  const call = (x, none) => (x && x.name ? `${x.name} ${JSON.stringify(x.args)}` : none);
  const expected = c ? call(c.expected, "no further call, the recorded run ended here") : "";
  const got = c ? call(c.got, "no call") : "";
  stage.append(el("div", { class: "panel report" },
    el("p", { text: `Every call recorded with ${nice(reg.recorded_version)} was replayed against ${nice(reg.changed_version)}. The replay serves each recorded tool answer and stops at the first step where the new build asks for something different.` }),
    el("div", { class: "kv" },
      el("span", { class: "h", text: "" }), el("span", { class: "h", text: "calls" }), el("span", { class: "h", text: "" }),
      "replayed", el("span", { class: "num", text: reg.replayed }), "",
      "stopped at a changed step", el("span", { class: "num", text: reg.diverged }), "",
      "goal lost when run on live", el("span", { class: "num", text: reg.lost_success }), "",
      "new hazard when run on live", el("span", { class: "num", text: reg.new_hazards }), ""),
    c ? el("div", { class: "card" },
      el("h4", { text: `One of them: ${c.scenario}, step ${c.step}` }),
      el("p", {}, "Recorded: ", el("code", { text: expected })),
      el("p", {}, "New build: ", el("code", { text: got })),
      el("p", { text: `Served up to that step and run live after it, the call went from ${c.success_before ? "goal met" : "goal not met"} to ${c.success_after ? "goal met" : "goal not met"}${c.hazards_after.length ? `, with hazard ${c.hazards_after.join(", ").replaceAll("_", " ")}` : ""}.` }),
      el("button", { type: "button", class: "drawer__close", onclick: () => openTranscript(c.scenario, "The call as recorded before the change.", reg.recorded_turns), text: "Read the recorded call" })) : null));
}

// ---------------------------------------------------------------- adversarial view

function renderAttacks(stage) {
  const d = state.data;
  const atts = d.attacks;
  const cand = d.comparison.candidate;
  const hz = atts.filter((a) => a.candidate_hazards.length).length;
  const planted = atts.reduce((s, a) => s + a.planted_calls.length, 0);
  const lines = [`${atts.length} adversarial personas from the page's sample, replayed on ${nice(cand)}.`];
  if (planted) {
    const res = atts.reduce((s, a) => s + (a.blocked_by_resolver || 0), 0);
    const srv = atts.reduce((s, a) => s + (a.blocked_by_server || 0), 0);
    lines.push(`They tried ${planted} planted tool calls: the agent's resolver refused ${res} before sending, Warden's server refused ${srv}.`);
  }
  lines.push(hz ? `${hz} still caused a hazard.` : "None caused a hazard.");
  stage.append(el("div", { class: "panel summary", text: lines.join(" ") }));
  const list = el("div", { class: "list" });
  atts.forEach((a) => {
    const chips = [
      ...a.planted_calls.map((t) => el("span", { class: "chip", text: t })),
      ...a.candidate_hazards.map((h) => el("span", { class: "chip bad", text: h.replaceAll("_", " ") })),
    ];
    list.append(el("button", { type: "button", class: "panel attack",
      onclick: () => openTranscript(a.id, `${a.kind.replaceAll("_", " ")} on ${nice(cand)}`, a.turns) },
    el("div", {}, el("strong", { text: a.kind.replaceAll("_", " ") }),
      a.lines.length ? el("q", { text: a.lines[0] }) : el("q", { text: "Planted in the tool results, not said by the customer." }),
      chips.length ? el("div", { class: "chips" }, chips) : null),
    el("span", { class: `badge ${a.candidate_hazards.length ? "hold" : "pass"}`, text: a.candidate_hazards.length ? "got through" : "blocked" })));
  });
  stage.append(list);
}

boot().catch((e) => {
  $("#stage").replaceChildren(el("p", { class: "empty", text: `Could not load the recorded runs: ${e.message}` }));
});
