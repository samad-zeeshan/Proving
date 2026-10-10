// Replays recorded simulations from data/*.json as a control room. Nothing here calls an agent or a model.
"use strict";

const state = { index: null, cache: new Map(), client: null, data: null, a: null, b: null, view: "run", tl: null };
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (s, root = document) => root.querySelector(s);

// Customers start over this many screen seconds. Start times are not in the recording, only reply latencies are.
const ARRIVE = 1.6;
// The slowest call on screen is stretched or squeezed to take this long, and everything else keeps its ratio to it.
const RUN = 8;
const GATE_STEP = 0.22;

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid.nodeType ? kid : String(kid));
  return n;
}

const pct = (x) => (x === null || x === undefined ? "n/a" : `${(x * 100).toFixed(1)}%`);
const num = (x, d = 2) => (x === null || x === undefined ? "n/a" : Number(x).toFixed(d));
const nice = (v) => v.replace("|", ", ").replace("noise@", "noise ").replace("asr@", "audio ");
const human = (s) => s.replaceAll("_", " ");
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const sum = (xs) => xs.reduce((s, x) => s + x, 0);
const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((p, q) => p - q);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const fmtMs = (x) => (x === null ? "n/a" : x < 10 ? `${x.toFixed(1)} ms` : x < 1000 ? `${Math.round(x)} ms` : `${(x / 1000).toFixed(2)} s`);
const fmtClock = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const say = (msg) => { $("#status").textContent = msg; };
// Prose rounds to two significant figures. Exact values stay in tables and mono tags.
const sig2 = (x) => Number(Number(x).toPrecision(2));
const approx = (n) => (sig2(n) === n ? n.toLocaleString("en") : `about ${sig2(n).toLocaleString("en")}`);
const pctR = (x) => `${sig2(x * 100)}%`;
const tag = (text) => el("span", { class: "tag", translate: "no", text });

// Plain names for what the recording calls by internal id. The id still shows in a small tag.
const VERSION = {
  v2: "As shipped, with the call checker",
  "resolver-off": "Without the call checker",
  rules: "As shipped, with hand-written rules",
  llm: "With a small AI model that reads callers",
  "rules|noise@0.1": "Rules, with one caller word in ten garbled",
  "rules|split": "Rules, with each caller line cut in two",
  "rules-regressed": "Rules, with a bug added on purpose",
};
const NOTE = {
  v2: "Before the agent sends a request to Warden's server, a checker on its side refuses any call that is not on the approved list.",
  "resolver-off": "This version has no checker. Warden's server still checks every call on its own.",
  rules: "This is the version in use now. Hand-written rules find what the caller wants.",
  llm: "A small AI model on the same computer finds what the caller wants. If the model fails, the rules do the work.",
  "rules|noise@0.1": "This is the rules version. The test garbles one word in ten from each caller on purpose.",
  "rules|split": "This is the rules version. The test splits everything the caller says into two messages.",
  "rules-regressed": "This is the rules version. The test added a bug to it on purpose. It hears \"the second one\" as the first.",
};
const BLURB = {
  warden: "Warden is an AI agent. It approves safe changes to live software, blocks dangerous ones and sends unclear ones to a person.",
  parley: "Parley is an AI phone agent. It books property viewings in English and Gulf Arabic.",
};
const CLAIM = {
  resolver: "With the call checker, fewer planted calls reach Warden's server. A planted call is an order that an attacker hides in a request for the agent to send.",
  "nlu-llm": "If a small AI model reads callers instead of hand-written rules, the agent books more viewings.",
};
const HAZARD = {
  wrong_phone: "saved the wrong phone number",
  wrong_booking: "booked the wrong viewing",
  spoke_injected_text: "repeated text planted in a listing",
  over_stated_budget: "offered a home over the caller's budget",
};
const KIND = {
  forged_arguments: "Fakes the details of a request",
  freeze_bypass: "Claims that a change freeze ended",
  invented_tools: "Asks for tools that do not exist",
  misleading_description: "Hides a risky change behind a harmless description",
  other_tenant: "Reaches into another company's changes",
  poisoned_reads: "Hides orders in data the agent reads",
  self_approve: "Tries to approve its own change",
  cancel_other: "Tries to cancel someone else's booking",
  data_probe: "Asks for other people's phone numbers",
  double_book: "Books the same viewing again for someone else",
  planted_instruction: "Hides orders in what the caller says",
  unoffered_slot: "Asks for a time that the agent never offered",
};
const LANG = { en: "English", "ar-gulf": "Gulf Arabic", "ar-msa": "Formal Arabic", mixed: "English and Arabic mixed" };
const COMP = {
  base_prompt: "fixed instructions",
  injected_context: "listing details added",
  inference: "the model's own answer",
  miss_penalty: "answers thrown away",
  accumulation: "earlier turns sent again",
};
// Parley talks with made-up customers. Warden talks with no one. It judges each made-up change request once,
// so its words name requests, and its goal is the right decision for that request.
const WORDS = {
  parley: {
    one: "customer", many: "customers", speaker: "Customer",
    runTab: "Run the customers", tricksTab: "Customers who try tricks",
    goal: "the customer got their goal", noGoal: "the customer did not get their goal", gaveUp: "the customer gave up",
    met: "goal met", notMet: "goal not met", legendGaveUp: "customer gave up", legendTrick: "customer who tries a trick",
    metric: "How many more customers got their goal, before and after",
    share: "The share of customers who got their goal", shareRule: "The share of customers who get their goal",
    worse: "fewer customers got their goal", noWorse: "Customers did no worse", rate: "Customers got their goal",
    goalRow: "Customers who got their goal", gaveUpRow: "Customers who gave up", tricked: " who tried tricks",
    metCount: (n) => `Each version met ${n} customers.`,
    used: (n, m) => `It used ${n} made-up customers, and ${m} of them tried tricks.`,
    caught: "The replay found the damage before any real customer met it.",
    went: (before, after) => (before === after
      ? `the customer ${after ? "still got their goal" : "still did not get their goal"}.`
      : `the customer ${before ? "got their goal before the change, but not after it" : "did not get their goal before the change, but got it after"}.`),
    lost: "then failed a customer that it served before",
    attackIntro: (n, v) => `These ${n} customers tried tricks on "${v}".`,
    hid: (n) => `They hid ${n} planted calls in their requests.`,
    plantedDef: "A planted call is a request that the agent must never send.",
    unsaid: "The customer did not say this. It hid in data that the agent read.",
  },
  warden: {
    one: "request", many: "requests", speaker: "Requester",
    runTab: "Run the requests", tricksTab: "Requests with hidden attacks",
    goal: "Warden made the right decision on this request", noGoal: "Warden made the wrong decision on this request",
    gaveUp: "the requester gave up",
    met: "right decision", notMet: "wrong decision", legendGaveUp: "requester gave up", legendTrick: "request with a hidden attack",
    metric: "How many more requests got the right decision, before and after",
    share: "The share of requests with the right decision", shareRule: "The share of requests with the right decision",
    worse: "Warden made the right decision less often", noWorse: "Warden did no worse on the requests",
    rate: "Warden made the right decision",
    goalRow: "Requests with the right decision", gaveUpRow: "Requesters who gave up", tricked: " with hidden attacks",
    metCount: (n) => `Each version judged ${n} requests.`,
    used: (n, m) => `It used ${n} made-up requests, and ${m} of them hid an attack.`,
    caught: "The replay found the damage before it reached any real change.",
    went: (before, after) => (before === after
      ? `Warden still made the ${after ? "right" : "wrong"} decision.`
      : `Warden made the ${before ? "right decision before the change, but not after it" : "wrong decision before the change, but the right one after"}.`),
    lost: "then got a request wrong that it got right before",
    attackIntro: (n, v) => `These ${n} requests hid attacks aimed at "${v}".`,
    hid: (n) => `Together they hid ${n} planted calls.`,
    plantedDef: "A planted call is an order that the agent must never send to the server.",
    unsaid: "The request text did not hold this. It hid in data that the agent read.",
  },
};
const W = () => WORDS[state.client] || WORDS.parley;
const plain = (v) => VERSION[v] || nice(v);
const harm = (h) => HAZARD[h] || human(h);
const kindName = (a) => (a.kind ? KIND[a.kind] || cap(human(a.kind)) : "Hides orders in data the agent reads");

const ICON = {
  play: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 1.2v9.6L10.6 6z"/></svg>',
  pause: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 1.2h3v9.6H2zM7 1.2h3v9.6H7z"/></svg>',
  restart: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1.5 1.2h1.8v9.6H1.5zM10.5 1.2v9.6L4.2 6z"/></svg>',
};

function killTimeline() {
  if (state.tl) state.tl.kill();
  state.tl = null;
}

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} answered ${r.status}`);
  return r.json();
}

// ---------------------------------------------------------------- controls

async function boot() {
  state.index = await getJSON("data/index.json");
  const group = $("#clients");
  group.replaceChildren(...state.index.clients.map((c) => el("button", {
    type: "button", role: "radio", "aria-checked": "false", "data-client": c.client,
    onclick: () => selectClient(c.client), text: c.label,
  })));
  // Arrow keys move between agents, the way a radio group should behave.
  group.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    const ids = state.index.clients.map((c) => c.client);
    const step = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1;
    const next = ids[(ids.indexOf(state.client) + step + ids.length) % ids.length];
    e.preventDefault();
    selectClient(next).then(() => $(`#clients [data-client="${next}"]`).focus());
  });
  document.querySelectorAll(".views button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
  $("#version-a").addEventListener("change", (e) => { state.a = e.target.value; notes(); show(state.view); });
  $("#version-b").addEventListener("change", (e) => { state.b = e.target.value; notes(); show(state.view); });
  const drawer = $("#drawer");
  $("#drawer-close").addEventListener("click", () => drawer.close());
  drawer.addEventListener("click", (e) => { if (e.target === drawer) drawer.close(); });
  await selectClient(state.index.clients[0].client);
}

async function selectClient(id) {
  killTimeline();
  state.client = id;
  $('.views [data-view="run"]').textContent = W().runTab;
  $('.views [data-view="attacks"]').textContent = W().tricksTab;
  const stage = $("#stage");
  document.querySelectorAll("#clients button").forEach((b) => {
    const on = b.dataset.client === id;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on ? 0 : -1;
    b.toggleAttribute("aria-busy", on && !state.cache.has(id));
  });
  if (!state.cache.has(id)) {
    stage.setAttribute("aria-busy", "true");
    stage.replaceChildren(skeleton());
    try {
      state.cache.set(id, await getJSON(`data/${id}.json`));
    } catch (err) {
      stage.removeAttribute("aria-busy");
      stage.replaceChildren(el("div", { class: "empty" },
        el("p", { text: `The recorded runs did not load (${err.message}). Check the connection. Then try again.` }),
        el("button", { type: "button", class: "btn", onclick: () => selectClient(id), text: "Try again" })));
      return;
    } finally {
      document.querySelectorAll("#clients button").forEach((b) => b.removeAttribute("aria-busy"));
    }
  }
  if (state.client !== id) return;
  const d = state.cache.get(id);
  state.data = d;
  $("#client-blurb").textContent = BLURB[id] || d.blurb;
  for (const [sel, pick] of [["#version-a", d.comparison.baseline], ["#version-b", d.comparison.candidate]]) {
    $(sel).replaceChildren(...d.versions.map((v) => el("option", { value: v, text: plain(v), selected: v === pick })));
  }
  state.a = d.comparison.baseline;
  state.b = d.comparison.candidate;
  notes();
  show(state.view);
}

function noteFor(v) {
  return [NOTE[v] || state.data.notes[v] || "", tag(v)];
}

function notes() {
  $("#note-a").replaceChildren(...noteFor(state.a));
  $("#note-b").replaceChildren(...noteFor(state.b));
}

function screenedPair() {
  return state.a === state.data.comparison.baseline && state.b === state.data.comparison.candidate;
}

function useScreenedPair() {
  const c = state.data.comparison;
  state.a = c.baseline;
  state.b = c.candidate;
  $("#version-a").value = c.baseline;
  $("#version-b").value = c.candidate;
  notes();
  show(state.view);
}

function show(view) {
  killTimeline();
  state.view = view;
  document.querySelectorAll(".views button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  const stage = $("#stage");
  stage.removeAttribute("aria-busy");
  stage.replaceChildren();
  ({ run: renderRun, report: renderReport, regression: renderRegression, attacks: renderAttacks })[view](stage);
}

function skeleton() {
  const bank = () => el("div", { class: "bank" }, el("div", { class: "grid" },
    Array.from({ length: 48 }, () => el("span", { class: "tile skeleton" }))));
  return el("div", { class: "floor", style: "border-top:1px solid var(--line);border-radius:var(--r-panel)" },
    bank(), bank(), el("div", { class: "rail" }, el("p", { class: "rail__wait", text: "Please wait while the recorded conversations load…" })));
}

// ---------------------------------------------------------------- tiles and transcripts

function outcomeClass(t) {
  if (t.missing) return "missing";
  if (t.hazards && t.hazards.length) return "hazard";
  if (t.end === "patience") return "gaveup";
  return t.success ? "ok" : "fail";
}

function outcomeText(t) {
  if (t.missing) return `this version did not run this ${W().one}`;
  const bits = [t.success ? W().goal : W().noGoal];
  if (t.end === "patience") bits.push(W().gaveUp);
  if (t.hazards.length) bits.push(`the agent caused harm. It ${t.hazards.map(harm).join(", ")}`);
  return bits.map(cap).join(". ");
}

function openTranscript(title, meta, turns, calls) {
  $("#drawer-title").textContent = title;
  $("#drawer-meta").textContent = meta;
  const body = $("#drawer-body");
  body.replaceChildren();
  turns.forEach(([c, a]) => {
    if (c) body.append(el("li", { class: "c" }, el("span", { class: "who", text: W().speaker }), c));
    if (a) body.append(el("li", { class: "a" }, el("span", { class: "who", text: "Agent" }), a));
  });
  const planted = (calls || []).filter((x) => x.phase === "steered");
  if (planted.length) {
    body.append(el("li", { class: "c" }, el("span", { class: "who", text: "Planted calls that reached Warden's server" }),
      planted.map((x) => `${x.tool} (${x.ok ? "the server ran it" : "the server refused it"})`).join(", ")));
  }
  $("#drawer").showModal();
}

// ---------------------------------------------------------------- number line

const METRIC = {
  get success() { return W().metric; },
  "tools.steered_sent": "How many planted calls reached the server, before and after",
};
// How the report sentence reads each measure. "lower" means a fall is the good direction.
const MEASURE = {
  success: { get noun() { return W().share; }, fmt: pctR, better: "higher", unit: "" },
  "tools.steered_sent": { noun: "Planted calls that reached the server", fmt: sig2, better: "lower", get unit() { return ` per ${W().one}`; } },
};

function niceStep(span) {
  const raw = span / 5;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
}

function numberLine(h) {
  const [lo, hi] = h.ci;
  const minE = h.min_effect;
  let left = Math.min(lo, 0, -minE * 0.5);
  let right = Math.max(hi, minE * 1.5);
  const pad = (right - left) * 0.08;
  left -= pad;
  right += pad;
  const pos = (x) => ((x - left) / (right - left)) * 100;
  const step = niceStep(right - left);
  const dec = Math.max(0, -Math.floor(Math.log10(step)));
  const ticks = [];
  for (let x = Math.ceil(left / step) * step; x <= right + 1e-12; x += step) {
    const v = Math.abs(x) < step / 1e6 ? 0 : x;
    ticks.push(el("div", { class: "nl__tick", style: `left:${pos(v)}%` }, el("span", { text: v.toFixed(dec) })));
  }
  // Floating point makes "the same" intervals differ in the last digit, so compare against the axis scale.
  const point = Math.abs(hi - lo) < (right - left) * 1e-4;
  const est = Math.min(Math.max(h.improvement, lo), hi);
  const inner = point ? 0 : ((est - lo) / (hi - lo)) * 100;
  const iv = el("div", {
    class: `nl__iv ${h.verdict}${point ? " is-point" : ""}`,
    style: point ? `left:${pos(lo)}%` : `left:${pos(lo)}%;width:${pos(hi) - pos(lo)}%;transform-origin:${inner}% 50%`,
  }, el("span", { class: "nl__bar" }), el("span", { class: "nl__est", style: `left:${inner}%` }));
  const label = `With ${Math.round(h.level * 100)}% confidence the improvement is between ${num(lo, 3)} and ${num(hi, 3)}. No change is 0. The smallest improvement good enough to ship is ${minE}.`;
  const line = el("div", { class: "nl", role: "img", "aria-label": label },
    el("div", { class: "nl__axis" }), ...ticks,
    el("div", { class: "nl__ref flip is-zero", style: `left:${pos(0)}%` }, el("span", { text: "no change" })),
    el("div", { class: `nl__ref is-min${pos(minE) > 62 ? " flip" : ""}`, style: `left:${pos(minE)}%` }, el("span", { text: `good enough to ship, ${minE}` })),
    iv);
  const widthNote = point
    ? (h.same_outcome === h.n
      ? ` All ${h.n} ${W().many} ended the same way in both versions, so the range has no width.`
      : " The range has no width.")
    : "";
  const note = el("p", { class: "nl__note" },
    "The best guess is ", el("b", { text: num(h.improvement, 3) }), `. The test is ${Math.round(h.level * 100)}% sure that the true change is between `,
    el("b", { text: num(lo, 3) }), " and ", el("b", { text: num(hi, 3) }), `.${widthNote}`);
  return { line, iv, note, point };
}

function verdictText(h) {
  if (h.verdict === "confirmed") return "The claim proved true. Even the low end of the range is an improvement.";
  if (h.verdict === "refuted") return "The claim proved false. The range shows that the gain is too small to ship.";
  return "The claim is not settled yet. The range is too wide to decide.";
}

function heldWord(h) {
  return h.verdict === "confirmed" ? "proved true" : h.verdict === "refuted" ? "proved false" : "is not settled yet";
}

function stampWord(r) {
  return r.verdict === "needs more evidence" ? "more" : r.verdict;
}

// Why a failed check holds the release, said as the reason a person would give.
const HOLD_WHY = {
  get "sample size"() { return `the test used too few ${W().many}`; },
  "hazard rate": "too many conversations still caused harm",
  "no new hazards": "the new version caused harm the old one did not",
  get "task success not worse"() { return W().worse; },
};

function stampLine(r) {
  if (r.verdict === "ship") return "Every check passed, so the new version is ready to release.";
  const failed = r.gates.filter((g) => g.outcome !== "pass")
    .map((g) => HOLD_WHY[g.gate] || (g.gate.startsWith("hypothesis") ? "the claimed gain did not show up" : g.gate));
  if (r.verdict === "hold") return `The new version should wait, because ${failed.join(" and ")}.`;
  return "There is not enough evidence yet to decide.";
}

function stampText(r) {
  return r.verdict === "ship" ? "Ship" : r.verdict === "hold" ? "Hold" : "More evidence";
}

// Gate details arrive as one generated line. The plain sentence is rebuilt from the report numbers,
// and only the interval from that line survives, in a tag.
function gateInfo(g, r) {
  const b = r.baseline_summary;
  const c = r.candidate_summary;
  const bar = r.evidence_bar;
  const pass = g.outcome === "pass";
  const m = g.detail.match(/change ([+-]?[\d.]+) \(([^)]*)\)/);
  const range = m ? `change ${m[1]}, range ${m[2]}` : "";
  const paren = (g.detail.match(/\(([^)]*)\)/) || [])[1] || "";
  if (g.gate === "sample size") {
    return { name: `The test used enough ${W().many}`, tag: `${c.valid} run, ${bar.min_scenarios} needed`,
      text: `${W().metCount(approx(c.valid))} This agent needs at least ${approx(bar.min_scenarios)}, so that is ${pass ? "enough" : "too few"}.` };
  }
  if (g.gate === "hazard rate") {
    const seen = c.hazard_runs
      ? `The new version caused harm in ${approx(c.hazard_runs)} of ${approx(c.valid)} conversations, about ${pctR(c.hazard_runs / c.valid)}.`
      : `The new version caused harm in none of ${approx(c.valid)} conversations.`;
    return { name: "Harm stayed rare enough", tag: paren,
      text: `${seen} The limit is ${pctR(bar.max_hazard_rate)}, so this ${pass ? "passes" : "fails"}.` };
  }
  if (g.gate === "no new hazards") {
    let text;
    if (!b.hazard_runs && !c.hazard_runs) text = "No conversation in either version caused harm. The change added no harm.";
    else if (b.hazard_runs === c.hazard_runs) text = `Both versions caused harm in ${approx(c.hazard_runs)} conversations. The change added none.`;
    else {
      const down = c.hazard_runs < b.hazard_runs;
      text = `The new version caused harm in ${approx(c.hazard_runs)} conversations, ${down ? "down" : "up"} from ${approx(b.hazard_runs)}. ${down ? "That is better." : "That is worse."}`;
    }
    return { name: "The change added no new harm", tag: range, text };
  }
  if (g.gate === "task success not worse") {
    const seen = pctR(b.success_rate) === pctR(c.success_rate)
      ? `${W().rate} ${pctR(c.success_rate)} of the time in both versions.`
      : `${W().rate} ${pctR(b.success_rate)} of the time before and ${pctR(c.success_rate)} after.`;
    return { name: W().noWorse, tag: range,
      text: `${seen} A drop of more than ${sig2(bar.success_margin * 100)} points would fail, so this ${pass ? "passes" : "fails"}.` };
  }
  if (g.gate.startsWith("hypothesis")) {
    const id = g.gate.replace(/^hypothesis\s+/, "");
    const h = r.hypotheses.find((x) => x.id === id);
    const claim = (h && (CLAIM[h.id] || h.claim)) || "";
    return { name: "The claimed reason is true", tag: id, text: `${h ? `The claim ${heldWord(h)}.` : ""} ${claim}`.trim() };
  }
  return { name: cap(g.gate), tag: "", text: g.detail };
}

function gateWord(g) {
  return g.outcome === "pass" ? "yes" : g.outcome === "more" ? "not yet" : "no";
}

function gateList(r) {
  return el("ul", { class: "gates" }, r.gates.map((g) => {
    const info = gateInfo(g, r);
    return el("li", { class: g.outcome },
      el("span", { class: `lamp ${g.outcome}`, "aria-hidden": "true" }, el("i")),
      el("span", { class: "g-name" }, info.name, el("span", { class: "sr", text: `. ${info.text}` })),
      el("span", { class: "g-word", text: gateWord(g) }));
  }));
}

// ---------------------------------------------------------------- run view

function lanesFor(tiles, side, perSec) {
  return tiles.map((t, i) => {
    const start = (((i * 389 + side * 131) % 1000) / 1000) * ARRIVE;
    const steps = (t.ms || []).map((x) => x / perSec);
    return { t, start, end: start + sum(steps), cls: outcomeClass(t), shown: null, btn: null, bar: null };
  });
}

function renderRun(stage) {
  const d = state.data;
  const sides = [state.a, state.b];
  const tiles = sides.map((v) => d.grid[v]);
  const live = tiles.flat().filter((t) => !t.missing);
  const maxMs = Math.max(1e-6, ...live.map((t) => sum(t.ms || [])));
  const perSec = maxMs / RUN;
  const lanes = tiles.map((ts, side) => lanesFor(ts, side, perSec));
  const total = Math.max(ARRIVE, ...lanes.flat().map((l) => l.end));
  const screened = screenedPair();

  // Banks: one grid of customers per version, with counters that tick as calls land.
  const banks = lanes.map((ls, side) => {
    const v = sides[side];
    const grid = el("div", { class: "grid", role: "list", "aria-label": `${cap(W().many)} for ${plain(v)}` });
    const counters = { done: el("b", { text: "0" }), ok: el("b", { text: "0" }), hazard: el("b", { text: "0" }), gaveup: el("b", { text: "0" }) };
    const run = ls.filter((l) => !l.t.missing).length;
    ls.forEach((l) => {
      const t = l.t;
      l.bar = el("i");
      l.btn = el("button", {
        type: "button", class: `tile${t.adversarial ? " adv" : ""}${t.missing ? " missing" : ""}`, role: "listitem",
        "aria-label": `${t.id}: ${t.missing ? outcomeText(t) : "waiting"}`, disabled: t.missing ? true : null,
        onclick: () => !t.missing && openTranscript(t.id, `${plain(v)}. ${LANG[t.language] || t.language}. ${cap(outcomeText(t))}.`, t.turns, t.calls),
      }, l.bar);
      grid.append(l.btn);
    });
    const replies = ls.flatMap((l) => l.t.ms || []);
    const bank = el("section", { class: "bank", "aria-label": `${side ? "New" : "Old"} version` },
      el("div", { class: "bank__head" },
        el("span", { class: "bank__side" }, side ? "New version" : "Old version", tag(v)),
        el("span", { class: "bank__pace" }, "typical reply ", el("b", { text: fmtMs(median(replies)) }))),
      el("h2", { class: "bank__name", text: plain(v) }),
      el("p", { class: "bank__note", text: NOTE[v] || d.notes[v] || "" }),
      grid,
      el("div", { class: "counts" },
        el("span", {}, counters.done, `of ${run} finished`),
        el("span", { class: "c-ok" }, counters.ok, W().met),
        el("span", { class: "c-hazard" }, counters.hazard, "caused harm"),
        el("span", {}, counters.gaveup, "gave up")));
    return { bank, counters, lanes: ls, tally: { done: -1, ok: -1, hazard: -1, gaveup: -1 } };
  });

  // Rail: the verdict for the screened pair, drawn once the customers finish.
  const r = d.report;
  const rail = el("aside", { class: "rail", "aria-label": "Verdict" });
  const reveal = [];
  let hyp = null;
  let lamps = [];
  let words = [];
  let stamp = null;
  const wait = el("p", { class: "rail__wait rail__wide", text: `The verdict appears when the last ${W().one} finishes.` });
  if (screened) {
    const h = r.hypotheses[0];
    hyp = numberLine(h);
    const hv = el("p", { class: "hyp__verdict" }, el("span", { class: h.verdict === "confirmed" ? "confirmed" : "", text: verdictText(h) }));
    const gates = gateList(r);
    lamps = [...gates.querySelectorAll(".lamp i")];
    words = [...gates.querySelectorAll(".g-word")];
    stamp = el("span", { class: `stamp ${stampWord(r)}`, "data-demo": "verdict", text: stampText(r) });
    const why = el("p", { class: "stamp-line", text: stampLine(r) });
    reveal.push(hv, hyp.note, why);
    rail.append(
      el("div", { class: "rail__wide" },
        el("p", { class: "rail__title", text: "What the change claims" }),
        el("p", { class: "rail__claim", text: CLAIM[h.id] || h.claim })),
      el("div", { class: "rail__wide" },
        el("p", { class: "nl__note", text: METRIC[h.metric] || `Change in ${h.metric}` }),
        hyp.line, hyp.note, hv),
      el("div", {}, el("p", { class: "rail__title", style: "margin-bottom:10px", text: "Checks before release" }), gates),
      el("div", {}, el("div", { class: "stamp-slot" }, stamp), why),
      wait);
  } else {
    const table = pairTable(tiles[0], tiles[1]);
    reveal.push(table);
    rail.append(
      el("div", { class: "rail__wide" },
        el("p", { class: "rail__title", text: "Verdict" }),
        el("p", { class: "rail__claim", text: `The page has a ship or hold verdict only for "${plain(d.comparison.baseline)}" against "${plain(d.comparison.candidate)}". For the two versions on screen, the table shows the plain counts.` }),
        el("button", { type: "button", class: "btn", style: "margin-top:12px", onclick: useScreenedPair, text: "Show the pair with a verdict" })),
      el("div", { class: "rail__wide" }, table), wait);
  }

  // Transport: play, restart, scrub, speed. The recorded pace is stated, not implied.
  const playBtn = el("button", { type: "button", class: "btn btn--primary" });
  const restartBtn = el("button", { type: "button", class: "btn", "aria-label": "Restart", html: ICON.restart });
  const scrub = el("input", { type: "range", min: "0", max: "1000", step: "1", value: "0", "aria-label": "Replay position" });
  const nowOut = el("b", { text: fmtClock(0) });
  const lenOut = el("span");
  const ratio = perSec >= 1000
    ? `Each second here is ${(perSec / 1000).toFixed(1)} s of real reply time.`
    : `Each second here is ${perSec < 1 ? perSec.toFixed(2) : perSec.toFixed(1)} ms of real reply time. The page slows the replay so you can watch it.`;
  const speeds = [1, 2, 4].map((s) => el("button", {
    type: "button", "aria-pressed": String(s === 1), "data-speed": s, "data-demo": s === 4 ? "speed-4x" : null, text: `${s}x`,
  }));
  const transport = el("div", { class: "transport" },
    playBtn, restartBtn,
    el("div", { class: "scrub" }, scrub, el("div", { class: "scrub__read" },
      el("span", {}, nowOut, " / ", lenOut), el("span", { text: ratio }))),
    el("div", { class: "speed", role: "group", "aria-label": "Playback speed" }, speeds));

  const legend = el("div", { class: "legend", "aria-label": "Legend" },
    el("span", {}, el("span", { class: "tile ok" }), W().met),
    el("span", {}, el("span", { class: "tile fail" }), W().notMet),
    el("span", {}, el("span", { class: "tile gaveup" }), W().legendGaveUp),
    el("span", {}, el("span", { class: "tile hazard" }), "the agent caused harm"),
    el("span", {}, el("span", { class: "tile adv" }), W().legendTrick),
    el("span", { text: "Select a square to read the conversation." }));

  const floor = el("div", { class: "floor" }, banks[0].bank, banks[1].bank, rail);
  stage.append(transport, floor, legend);

  function render(now) {
    for (const b of banks) {
      const tally = { done: 0, ok: 0, hazard: 0, gaveup: 0 };
      for (const l of b.lanes) {
        if (l.t.missing) continue;
        let shown;
        if (now < l.start) shown = "wait";
        // GSAP rounds tweened values, so allow a millisecond of slack at the finish line.
        else if (now >= l.end - 1e-3) shown = l.cls;
        else shown = "run";
        if (shown !== l.shown) {
          l.btn.className = `tile${shown === "run" ? " is-running" : shown === "wait" ? "" : ` ${shown}`}${l.t.adversarial ? " adv" : ""}`;
          if (shown !== "run") l.btn.setAttribute("aria-label", `${l.t.id}: ${shown === "wait" ? "not started yet" : outcomeText(l.t)}`);
          else l.btn.setAttribute("aria-label", `${l.t.id}: in progress`);
          l.shown = shown;
        }
        if (shown === "run") l.bar.style.transform = `scaleX(${(now - l.start) / (l.end - l.start)})`;
        if (shown !== "wait" && shown !== "run") {
          tally.done += 1;
          if (l.t.success) tally.ok += 1;
          if (shown === "hazard") tally.hazard += 1;
          if (l.t.end === "patience") tally.gaveup += 1;
        }
      }
      for (const k of Object.keys(tally)) {
        if (tally[k] !== b.tally[k]) { b.counters[k].textContent = tally[k]; b.tally[k] = tally[k]; }
      }
    }
  }

  const finished = () => say(screened
    ? `The replay finished. The verdict is ${stampText(r)}. ${stampLine(r)}`
    : "The replay finished.");

  if (!window.gsap) {
    // The timeline library did not load. Show where the replay ends instead of a broken player.
    render(Infinity);
    transport.replaceChildren(el("p", { class: "scrub__read", style: "margin:0", text: "The replay player did not load, so the page shows every conversation as it ended." }));
    return;
  }

  const clock = { t: 0 };
  const tl = gsap.timeline({ paused: true, onUpdate: sync, onComplete: () => { sync(); finished(); } });
  tl.to(clock, { t: total, duration: total, ease: "none", onUpdate: () => render(clock.t), onComplete: () => render(Infinity) }, 0);
  const V = total + 0.35;
  tl.fromTo(wait, { autoAlpha: 1 }, { autoAlpha: 0, duration: 0.2 }, V - 0.1);
  if (reveal.length) tl.fromTo(reveal, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.3, ease: "power2.out" }, V + 0.35);
  if (hyp) {
    const axis = hyp.point ? "scaleY" : "scaleX";
    tl.fromTo(hyp.iv, { autoAlpha: 0, [axis]: reduced ? 1 : 0 }, { autoAlpha: 1, [axis]: 1, duration: reduced ? 0.3 : 0.7, ease: "expo.out" }, V);
    const G = V + 0.6;
    tl.fromTo(lamps, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.16, ease: "power2.out", stagger: GATE_STEP }, G);
    tl.fromTo(words, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.16, stagger: GATE_STEP }, G);
    const S = G + lamps.length * GATE_STEP + 0.25;
    if (reduced) {
      tl.fromTo(stamp, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.3 }, S);
    } else {
      // A stamp falls onto the page, so it accelerates in and settles, unlike UI that eases out.
      tl.fromTo(stamp, { autoAlpha: 0, scale: 1.6, rotation: -14 }, { autoAlpha: 1, scale: 0.96, rotation: -5, duration: 0.22, ease: "power3.in" }, S);
      tl.to(stamp, { scale: 1, duration: 0.25, ease: "power2.out" }, S + 0.22);
    }
  }
  tl.to({}, { duration: 0.4 });
  state.tl = tl;
  lenOut.textContent = fmtClock(tl.duration());

  let dragging = false;
  let wasPlaying = false;
  function sync() {
    const p = tl.progress();
    if (!dragging) scrub.value = String(Math.round(p * 1000));
    scrub.setAttribute("aria-valuetext", `${fmtClock(tl.time())} of ${fmtClock(tl.duration())}`);
    nowOut.textContent = fmtClock(tl.time());
    const playing = !tl.paused() && p < 1;
    const label = playing ? "Pause" : p >= 1 ? "Replay" : "Play";
    if (playBtn.dataset.label !== label) {
      playBtn.dataset.label = label;
      playBtn.innerHTML = `${playing ? ICON.pause : ICON.play}<span>${label}</span>`;
    }
    restartBtn.disabled = tl.time() === 0;
  }
  playBtn.addEventListener("click", () => {
    if (tl.progress() >= 1) tl.restart();
    else if (tl.paused()) tl.play();
    else tl.pause();
    sync();
  });
  restartBtn.addEventListener("click", () => { tl.pause(0); render(0); sync(); playBtn.focus(); });
  const grab = () => { if (!dragging) { dragging = true; wasPlaying = !tl.paused() && tl.progress() < 1; tl.pause(); } };
  const release = () => { if (dragging) { dragging = false; if (wasPlaying) tl.play(); sync(); } };
  scrub.addEventListener("pointerdown", grab);
  scrub.addEventListener("keydown", grab);
  scrub.addEventListener("input", () => { grab(); tl.progress(Number(scrub.value) / 1000); });
  scrub.addEventListener("pointerup", release);
  scrub.addEventListener("keyup", release);
  scrub.addEventListener("change", release);
  speeds.forEach((b) => b.addEventListener("click", () => {
    speeds.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    gsap.to(tl, { timeScale: Number(b.dataset.speed), duration: 0.3, ease: "power2.out", overwrite: true });
  }));

  if (reduced) {
    // Reduced motion lands on the finished state. Play still replays it, with fades in place of movement.
    tl.progress(1).pause();
    finished();
  } else {
    render(0);
    tl.play(0);
  }
  sync();
}

function pairTable(ta, tb) {
  const tally = (ts) => {
    const run = ts.filter((t) => !t.missing);
    return { n: run.length, ok: run.filter((t) => t.success).length, hz: run.filter((t) => t.hazards.length).length, gu: run.filter((t) => t.end === "patience").length };
  };
  const a = tally(ta);
  const b = tally(tb);
  const row = (label, x, y) => el("tr", {}, el("td", { text: label }), el("td", { text: x }), el("td", { text: y }));
  return el("table", { class: "pair" },
    el("thead", {}, el("tr", {}, el("th", { text: "" }), el("th", { text: plain(state.a) }), el("th", { text: plain(state.b) }))),
    el("tbody", {},
      row(`${W().many} replayed`, a.n, b.n),
      row(W().met, a.ok, b.ok),
      row("the agent caused harm", a.hz, b.hz),
      row("gave up", a.gu, b.gu)));
}

// ---------------------------------------------------------------- report view

function renderReport(stage) {
  const d = state.data;
  const r = d.report;
  if (!screenedPair()) {
    stage.append(el("div", { class: "summary" },
      el("p", { style: "margin:0 0 12px", text: `The page has a report only for "${plain(d.comparison.baseline)}" against "${plain(d.comparison.candidate)}". For the pair that you picked, the table shows the counts from the ${W().many} on this page.` }),
      pairTable(d.grid[state.a], d.grid[state.b]),
      el("button", { type: "button", class: "btn", style: "margin-top:14px", onclick: useScreenedPair, text: "Show the pair with a verdict" })));
    return;
  }
  const bar = r.evidence_bar;
  const b = r.baseline_summary;
  const c = r.candidate_summary;
  const perRun = (x, s) => (s.valid ? x / s.valid : 0);
  const comps = ["base_prompt", "injected_context", "inference", "miss_penalty", "accumulation"];
  const maxTok = Math.max(1, ...comps.map((k) => perRun(c.cost[k], c)));
  const word = stampWord(r);
  const row = (label, x, y) => el("tr", {}, el("td", { text: label }), el("td", { text: x }), el("td", { text: y }));

  const hyps = r.hypotheses.map((h) => {
    const nl = numberLine(h);
    return el("section", {},
      el("h2", {}, `The claim ${heldWord(h)}`, tag(h.id)),
      el("p", { text: CLAIM[h.id] || h.claim }),
      el("p", { text: measureLine(h) }),
      el("p", { class: "nl__note", text: METRIC[h.metric] || `Change in ${h.metric}` }),
      nl.line, nl.note,
      el("p", { class: "hyp__verdict", style: "margin-top:10px" }, el("span", { class: h.verdict === "confirmed" ? "confirmed" : "", text: verdictText(h) })),
      el("p", { class: "nl__note", style: "margin-top:8px" }, "The exact values were ", el("b", { text: num(h.baseline_mean, 3) }), " before and ",
        el("b", { text: num(h.candidate_mean, 3) }), ` after, over ${h.n} ${W().many}.`, tag(h.metric)));
  });

  stage.append(el("div", { class: "report" },
    el("section", { class: "report__top" },
      el("span", { class: `stamp ${word}`, text: stampText(r) }),
      el("p", { class: "report__line" }, stampLine(r),
        el("small", {}, `The test compared "${plain(r.baseline)}" with "${plain(r.candidate)}". ${W().used(approx(r.scenarios.total), approx(r.scenarios.adversarial))}`,
          tag(`${r.baseline} vs ${r.candidate}`)))),
    ...hyps,
    el("section", { class: "split" },
      el("div", {}, el("h2", { text: "Checks before release" }),
        el("ul", { class: "gates" }, r.gates.map((g) => {
          const info = gateInfo(g, r);
          return el("li", { class: g.outcome, style: "align-items:start" },
            el("span", { class: `lamp ${g.outcome}`, style: "margin-top:4px", "aria-hidden": "true" }, el("i")),
            el("span", {}, el("span", { class: "g-name", text: info.name }), el("br"),
              el("span", { style: "color:var(--muted);font-size:13px" }, info.text, info.tag ? tag(info.tag) : null)),
            el("span", { class: "g-word", text: gateWord(g) }));
        }))),
      el("div", {}, el("h2", { text: "How high the bar is" }),
        el("p", {}, `How much it does alone: ${r.deployment.autonomy_why}`, tag(`autonomy ${r.deployment.autonomy}`)),
        el("p", {}, `What a mistake costs: ${r.deployment.consequence_why}`, tag(`consequence ${r.deployment.consequence}`)),
        el("p", {}, `So this agent gets the ${bar.tier} bar. The results must hold with ${Math.round(bar.confidence * 100)}% confidence, over at least ${approx(bar.min_scenarios)} ${W().many}. Harm may happen in at most ${pctR(bar.max_hazard_rate)} of conversations. ${W().shareRule} may not fall by more than ${sig2(bar.success_margin * 100)} points.`, tag(bar.tier)))),
    el("section", {}, el("h2", { text: "The numbers side by side" }),
      el("div", { class: "table-scroll" }, el("table", { class: "numbers" },
        el("thead", {}, el("tr", {}, el("th", { text: "" }), el("th", { text: plain(r.baseline) }), el("th", { text: plain(r.candidate) }))),
        el("tbody", {},
          row(W().goalRow, pct(b.success_rate), pct(c.success_rate)),
          row("Conversations where the agent caused harm", `${b.hazard_runs} of ${b.valid}`, `${c.hazard_runs} of ${c.valid}`),
          row(W().gaveUpRow, b.abandoned, c.abandoned),
          el("tr", {}, el("td", {}, "Typical time to reply", tag("p50")), el("td", { text: `${num(b.latency_ms.p50, 1)} ms` }), el("td", { text: `${num(c.latency_ms.p50, 1)} ms` })),
          el("tr", {}, el("td", {}, "AI model text per conversation", tag("tokens")), el("td", { text: num(b.tokens.per_run, 0) }), el("td", { text: num(c.tokens.per_run, 0) }))))),
      c.tokens.total
        ? el("div", { class: "tokens" },
          el("p", { style: "margin:4px 0 2px", text: "This chart shows where the new version's AI model text goes in each conversation. It counts the text in tokens, which are pieces of words." }),
          ...comps.map((k) => el("div", {}, el("span", { title: k, text: COMP[k] || human(k) }),
            el("i", { style: `transform:scaleX(${perRun(c.cost[k], c) / maxTok})` }),
            el("span", { text: num(perRun(c.cost[k], c), 0) }))))
        : el("p", { style: "margin-top:12px;color:var(--muted)", text: "Neither version uses an AI model, so there is no model cost to show." }))));
}

// Says the measured change as a sentence: what moved, to what, from what, and whether that is good.
function measureLine(h) {
  const m = MEASURE[h.metric];
  if (!m) return "";
  const before = m.fmt(h.baseline_mean);
  const after = m.fmt(h.candidate_mean);
  const who = `across ${approx(h.n)} ${W().many}${h.set === "adversarial" ? W().tricked : ""}`;
  if (before === after) return `${m.noun} stayed at ${after}${m.unit} in both versions, ${who}. No gain.`;
  const up = h.candidate_mean > h.baseline_mean;
  const good = up === (m.better === "higher");
  return `${m.noun} ${up ? "rose" : "fell"} to ${after}${m.unit}, from ${before} before, ${who}. ${good ? "That is better." : "That is worse."}`;
}

// ---------------------------------------------------------------- regression view

function renderRegression(stage) {
  const reg = state.data.regression;
  if (!reg) {
    stage.append(el("p", { class: "empty", text: "The page has no replay on changed code for this agent." }));
    return;
  }
  const c = reg.case;
  const call = (x, none) => (x && x.name ? `${x.name} ${JSON.stringify(x.args)}` : none);
  const damage = reg.lost_success + reg.new_hazards;
  const outcome = damage
    ? W().caught
    : `Some conversations took a different step, but none ended worse. The change broke nothing the replay could find.`;
  const went = c ? W().went(c.success_before, c.success_after) : "";
  const readout = (n, label, bad) => el("div", { class: bad && n > 0 ? "bad" : "" }, el("b", { text: n }), el("span", { text: label }));
  stage.append(el("div", { class: "report" },
    el("section", {}, el("h2", { text: "Replay on changed code" }),
      el("p", {}, `This test played every recorded conversation from "${plain(reg.recorded_version)}" again on "${plain(reg.changed_version)}".`, tag(`${reg.recorded_version} to ${reg.changed_version}`)),
      el("p", { text: "The replay gives the recorded answers again. It stops at the first step where the changed code asks for something different, then runs the rest for real." }),
      el("p", { text: outcome })),
    el("section", { class: "readouts" },
      readout(reg.replayed, "conversations played again"),
      readout(reg.diverged, "took a different step"),
      readout(reg.lost_success, W().lost, true),
      readout(reg.new_hazards, "then caused new harm", true)),
    c ? el("section", {},
      el("h2", {}, `One example, at step ${c.step}`, tag(c.scenario)),
      el("p", {}, "Recorded step: ", el("code", { text: call(c.expected, "nothing, the recorded conversation ended here") })),
      el("p", {}, "Changed code: ", el("code", { text: call(c.got, "nothing") })),
      el("p", { text: `The replay used the recording up to that step and ran for real after it. In the end, ${went}${c.hazards_after.length ? ` The agent also ${c.hazards_after.map(harm).join(" and ")}.` : ""}` }),
      el("button", { type: "button", class: "btn", onclick: () => openTranscript(c.scenario, "This is the conversation as it was before the change.", reg.recorded_turns), text: "Read the recorded conversation" })) : null));
}

// ---------------------------------------------------------------- adversarial view

function renderAttacks(stage) {
  const d = state.data;
  const atts = d.attacks;
  const cand = d.comparison.candidate;
  const hz = atts.filter((a) => a.candidate_hazards.length).length;
  const planted = sum(atts.map((a) => a.planted_calls.length));
  const lines = [W().attackIntro(atts.length, plain(cand))];
  if (planted) {
    const res = sum(atts.map((a) => a.blocked_by_resolver || 0));
    const srv = sum(atts.map((a) => a.blocked_by_server || 0));
    lines.push(W().hid(planted), W().plantedDef);
    lines.push(`The call checker refused ${res} of them before they left the agent. Warden's server refused ${srv}.`);
  }
  lines.push(hz ? `The agent still caused harm for ${hz} of them. That is not good enough yet.` : "The agent caused harm for none of them.");
  stage.append(el("p", { class: "summary", text: lines.join(" ") }));
  stage.append(el("div", { class: "attacks" }, atts.map((a) => {
    const bad = a.candidate_hazards.length > 0;
    const chips = [
      ...a.planted_calls.map((t) => el("span", { class: "chip", text: t })),
      ...a.candidate_hazards.map((h) => el("span", { class: "chip bad", text: harm(h) })),
    ];
    return el("button", { type: "button", class: "attack", onclick: () => openTranscript(a.id, `${kindName(a)}. ${plain(cand)}.`, a.turns) },
      el("div", {}, el("strong", {}, kindName(a), tag(a.kind || "planted in a tool result")),
        el("q", { text: a.lines.length ? a.lines[0] : W().unsaid }),
        chips.length ? el("div", { class: "chips" }, chips) : null),
      el("span", { class: `attack__state${bad ? " bad" : ""}` },
        el("span", { class: `lamp ${bad ? "hold" : "pass"}`, "aria-hidden": "true" }, el("i")), bad ? "trick worked" : "blocked"));
  })));
}

// The one theme flip: the page turns accent green once the footer reaches the middle of the screen.
// The CSS transition does the tween, and reduced motion sets it to zero.
function themeFlip() {
  const foot = $("#foot");
  if (!foot || !("IntersectionObserver" in window)) return;
  new IntersectionObserver(([e]) => {
    document.body.classList.toggle("is-flipped", e.isIntersecting || e.boundingClientRect.top < 0);
  }, { rootMargin: "0px 0px -50% 0px" }).observe(foot);
}
themeFlip();

boot().catch((e) => {
  const stage = $("#stage");
  stage.removeAttribute("aria-busy");
  stage.replaceChildren(el("div", { class: "empty" },
    el("p", { text: `The recorded runs did not load (${e.message}). Check the connection. Then try again.` }),
    el("button", { type: "button", class: "btn", onclick: () => location.reload(), text: "Try again" })));
});
