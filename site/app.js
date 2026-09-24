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
        el("p", { text: `The recorded runs did not load (${err.message}). Check the connection and try again.` }),
        el("button", { type: "button", class: "btn", onclick: () => selectClient(id), text: "Try again" })));
      return;
    } finally {
      document.querySelectorAll("#clients button").forEach((b) => b.removeAttribute("aria-busy"));
    }
  }
  if (state.client !== id) return;
  const d = state.cache.get(id);
  state.data = d;
  $("#client-blurb").textContent = d.blurb;
  for (const [sel, pick] of [["#version-a", d.comparison.baseline], ["#version-b", d.comparison.candidate]]) {
    $(sel).replaceChildren(...d.versions.map((v) => el("option", { value: v, text: nice(v), selected: v === pick })));
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
    bank(), bank(), el("div", { class: "rail" }, el("p", { class: "rail__wait", text: "Loading the recorded runs…" })));
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
  if (t.hazards.length) bits.push(`hazard: ${t.hazards.map(human).join(", ")}`);
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
  const planted = (calls || []).filter((x) => x.phase === "steered");
  if (planted.length) {
    body.append(el("li", { class: "c" }, el("span", { class: "who", text: "Planted calls that reached the server" }),
      planted.map((x) => `${x.tool} (${x.ok ? "ran" : "refused"})`).join(", ")));
  }
  $("#drawer").showModal();
}

// ---------------------------------------------------------------- number line

const METRIC = {
  success: "Gain in task success rate",
  "tools.steered_sent": "Drop in planted calls reaching the server, per scenario",
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
  const label = `${Math.round(h.level * 100)}% interval for the improvement, ${num(lo, 3)} to ${num(hi, 3)}. No change is 0, the smallest gain worth shipping is ${minE}.`;
  const line = el("div", { class: "nl", role: "img", "aria-label": label },
    el("div", { class: "nl__axis" }), ...ticks,
    el("div", { class: "nl__ref flip is-zero", style: `left:${pos(0)}%` }, el("span", { text: "no change" })),
    el("div", { class: `nl__ref is-min${pos(minE) > 62 ? " flip" : ""}`, style: `left:${pos(minE)}%` }, el("span", { text: `worth shipping, ${minE}` })),
    iv);
  const widthNote = point
    ? (h.same_outcome === h.n
      ? ` Width zero: all ${h.n} paired scenarios ended the same way in both versions.`
      : " Width zero.")
    : "";
  const note = el("p", { class: "nl__note" },
    "improvement ", el("b", { text: num(h.improvement, 3) }), `, ${Math.round(h.level * 100)}% interval `,
    el("b", { text: num(lo, 3) }), " to ", el("b", { text: num(hi, 3) }), `.${widthNote}`);
  return { line, iv, note, point };
}

function verdictText(h) {
  if (h.verdict === "confirmed") return "Confirmed. The whole interval is above zero.";
  if (h.verdict === "refuted") return `Refuted. The interval rules out a gain of ${h.min_effect} or more.`;
  return "Not settled. The interval is too wide to call either way.";
}

function stampWord(r) {
  return r.verdict === "needs more evidence" ? "more" : r.verdict;
}

function stampLine(r) {
  const why = r.verdict_line.replace(/^[^:]+:\s*/, "");
  return `${cap(why)}.`;
}

function gateList(gates, withDetail) {
  return el("ul", { class: "gates" }, gates.map((g) => el("li", { class: g.outcome },
    el("span", { class: `lamp ${g.outcome}`, "aria-hidden": "true" }, el("i")),
    el("span", { class: "g-name" }, cap(g.gate), withDetail ? el("span", { class: "sr", text: `. ${g.detail}` }) : null),
    el("span", { class: "g-word", text: g.outcome === "more" ? "more" : g.outcome }))));
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
    const grid = el("div", { class: "grid", role: "list", "aria-label": `Customers for ${nice(v)}` });
    const counters = { done: el("b", { text: "0" }), ok: el("b", { text: "0" }), hazard: el("b", { text: "0" }), gaveup: el("b", { text: "0" }) };
    const run = ls.filter((l) => !l.t.missing).length;
    ls.forEach((l) => {
      const t = l.t;
      l.bar = el("i");
      l.btn = el("button", {
        type: "button", class: `tile${t.adversarial ? " adv" : ""}${t.missing ? " missing" : ""}`, role: "listitem",
        "aria-label": `${t.id}: ${t.missing ? outcomeText(t) : "waiting"}`, disabled: t.missing ? true : null,
        onclick: () => !t.missing && openTranscript(t.id, `${nice(v)}. ${t.language}. ${cap(outcomeText(t))}.`, t.turns, t.calls),
      }, l.bar);
      grid.append(l.btn);
    });
    const replies = ls.flatMap((l) => l.t.ms || []);
    const bank = el("section", { class: "bank", "aria-label": `${side ? "Candidate" : "Current"} version` },
      el("div", { class: "bank__head" },
        el("span", { class: "bank__side", text: side ? "Candidate" : "Current" }),
        el("span", { class: "bank__pace" }, "median reply ", el("b", { text: fmtMs(median(replies)) }))),
      el("h2", { class: "bank__name", translate: "no", text: nice(v) }),
      el("p", { class: "bank__note", text: d.notes[v] || "" }),
      grid,
      el("div", { class: "counts" },
        el("span", {}, counters.done, `of ${run} done`),
        el("span", { class: "c-ok" }, counters.ok, "goal met"),
        el("span", { class: "c-hazard" }, counters.hazard, "hazard"),
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
  const wait = el("p", { class: "rail__wait rail__wide", text: "The verdict appears when the last customer finishes." });
  if (screened) {
    const h = r.hypotheses[0];
    hyp = numberLine(h);
    const hv = el("p", { class: "hyp__verdict" }, el("span", { class: h.verdict === "confirmed" ? "confirmed" : "", text: verdictText(h) }));
    const gates = gateList(r.gates, true);
    lamps = [...gates.querySelectorAll(".lamp i")];
    words = [...gates.querySelectorAll(".g-word")];
    stamp = el("span", { class: `stamp ${stampWord(r)}`, text: stampWord(r) === "more" ? "More evidence" : r.verdict });
    const stampText = el("p", { class: "stamp-line", text: stampLine(r) });
    reveal.push(hv, hyp.note, stampText);
    rail.append(
      el("div", { class: "rail__wide" },
        el("p", { class: "rail__title", text: "Hypothesis" }),
        el("p", { class: "rail__claim", text: h.claim })),
      el("div", { class: "rail__wide" },
        el("p", { class: "nl__note", text: METRIC[h.metric] || `Improvement in ${h.metric}` }),
        hyp.line, hyp.note, hv),
      el("div", {}, el("p", { class: "rail__title", style: "margin-bottom:10px", text: "Gates" }), gates),
      el("div", {}, el("div", { class: "stamp-slot" }, stamp), stampText),
      wait);
  } else {
    const table = pairTable(tiles[0], tiles[1]);
    reveal.push(table);
    rail.append(
      el("div", { class: "rail__wide" },
        el("p", { class: "rail__title", text: "Verdict" }),
        el("p", { class: "rail__claim", text: `The ship or hold report covers ${nice(d.comparison.baseline)} against ${nice(d.comparison.candidate)}, the change this agent was screened for. For the pair on screen, these are the counts.` }),
        el("button", { type: "button", class: "btn", style: "margin-top:12px", onclick: useScreenedPair, text: "Show the screened pair" })),
      el("div", { class: "rail__wide" }, table), wait);
  }

  // Transport: play, restart, scrub, speed. The recorded pace is stated, not implied.
  const playBtn = el("button", { type: "button", class: "btn btn--primary" });
  const restartBtn = el("button", { type: "button", class: "btn", "aria-label": "Restart", html: ICON.restart });
  const scrub = el("input", { type: "range", min: "0", max: "1000", step: "1", value: "0", "aria-label": "Replay position" });
  const nowOut = el("b", { text: fmtClock(0) });
  const lenOut = el("span");
  const ratio = perSec >= 1000
    ? `1 s here is ${(perSec / 1000).toFixed(1)} s of recorded reply time`
    : `1 s here is ${perSec < 1 ? perSec.toFixed(2) : perSec.toFixed(1)} ms of recorded reply time, slowed down`;
  const speeds = [1, 2, 4].map((s) => el("button", { type: "button", "aria-pressed": String(s === 1), "data-speed": s, text: `${s}x` }));
  const transport = el("div", { class: "transport" },
    playBtn, restartBtn,
    el("div", { class: "scrub" }, scrub, el("div", { class: "scrub__read" },
      el("span", {}, nowOut, " / ", lenOut), el("span", { text: ratio }))),
    el("div", { class: "speed", role: "group", "aria-label": "Playback speed" }, speeds));

  const legend = el("div", { class: "legend", "aria-label": "Legend" },
    el("span", {}, el("span", { class: "tile ok" }), "goal met"),
    el("span", {}, el("span", { class: "tile fail" }), "goal not met"),
    el("span", {}, el("span", { class: "tile gaveup" }), "customer gave up"),
    el("span", {}, el("span", { class: "tile hazard" }), "hazard"),
    el("span", {}, el("span", { class: "tile adv" }), "adversarial persona"),
    el("span", { text: "Select a square to read the call." }));

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
          if (shown !== "run") l.btn.setAttribute("aria-label", `${l.t.id}: ${shown === "wait" ? "waiting" : outcomeText(l.t)}`);
          else l.btn.setAttribute("aria-label", `${l.t.id}: running`);
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
    ? `Replay finished. ${r.verdict === "ship" ? "Ship" : r.verdict === "hold" ? "Hold" : "Needs more evidence"}. ${stampLine(r)}`
    : "Replay finished.");

  if (!window.gsap) {
    // The timeline library did not load. Show where the replay ends instead of a broken player.
    render(Infinity);
    transport.replaceChildren(el("p", { class: "scrub__read", style: "margin:0", text: "The replay player did not load, so this is the end state of every call." }));
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
    el("thead", {}, el("tr", {}, el("th", { text: "" }), el("th", { text: nice(state.a) }), el("th", { text: nice(state.b) }))),
    el("tbody", {},
      row("customers replayed", a.n, b.n),
      row("goal met", a.ok, b.ok),
      row("with a hazard", a.hz, b.hz),
      row("gave up", a.gu, b.gu)));
}

// ---------------------------------------------------------------- report view

function renderReport(stage) {
  const d = state.data;
  const r = d.report;
  if (!screenedPair()) {
    stage.append(el("div", { class: "summary" },
      el("p", { style: "margin:0 0 12px", text: `The report is written for ${nice(d.comparison.baseline)} against ${nice(d.comparison.candidate)}, the change this agent was screened for. For the pair you picked, these are the counts from the customers on this page.` }),
      pairTable(d.grid[state.a], d.grid[state.b]),
      el("button", { type: "button", class: "btn", style: "margin-top:14px", onclick: useScreenedPair, text: "Show the screened pair" })));
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
      el("h2", { text: `Hypothesis: ${h.verdict}` }),
      el("p", { text: h.claim }),
      el("p", { class: "nl__note", text: METRIC[h.metric] || `Improvement in ${h.metric}` }),
      nl.line, nl.note,
      el("p", { class: "hyp__verdict", style: "margin-top:10px" }, el("span", { class: h.verdict === "confirmed" ? "confirmed" : "", text: verdictText(h) })),
      el("p", { class: "nl__note", style: "margin-top:8px" }, `${h.metric}: `, el("b", { text: num(h.baseline_mean, 3) }), " before, ",
        el("b", { text: num(h.candidate_mean, 3) }), ` after, over ${h.n} scenarios.`));
  });

  stage.append(el("div", { class: "report" },
    el("section", { class: "report__top" },
      el("span", { class: `stamp ${word}`, text: word === "more" ? "More evidence" : r.verdict }),
      el("p", { class: "report__line" }, stampLine(r),
        el("small", { text: `${nice(r.baseline)} against ${nice(r.candidate)}, ${r.scenarios.total} scenarios, ${r.scenarios.adversarial} of them adversarial.` }))),
    ...hyps,
    el("section", { class: "split" },
      el("div", {}, el("h2", { text: "Gates" }),
        el("ul", { class: "gates" }, r.gates.map((g) => el("li", { class: g.outcome, style: "align-items:start" },
          el("span", { class: `lamp ${g.outcome}`, style: "margin-top:4px", "aria-hidden": "true" }, el("i")),
          el("span", {}, el("span", { class: "g-name", text: cap(g.gate) }), el("br"),
            el("span", { style: "color:var(--muted);font-size:13px", text: g.detail })),
          el("span", { class: "g-word", text: g.outcome }))))),
      el("div", {}, el("h2", { text: "Evidence bar" }),
        el("p", { text: `Autonomy ${r.deployment.autonomy}: ${r.deployment.autonomy_why}` }),
        el("p", { text: `Consequence ${r.deployment.consequence}: ${r.deployment.consequence_why}` }),
        el("p", { text: `So the bar is ${bar.tier}: ${Math.round(bar.confidence * 100)}% confidence, at least ${bar.min_scenarios} scenarios, hazards in at most ${pct(bar.max_hazard_rate)} of calls, and task success may not fall more than ${pct(bar.success_margin)}.` }))),
    el("section", {}, el("h2", { text: "Numbers" }),
      el("div", { class: "table-scroll" }, el("table", { class: "numbers" },
        el("thead", {}, el("tr", {}, el("th", { text: "" }), el("th", { text: nice(r.baseline) }), el("th", { text: nice(r.candidate) }))),
        el("tbody", {},
          row("task success", pct(b.success_rate), pct(c.success_rate)),
          row("calls with a hazard", `${b.hazard_runs} of ${b.valid}`, `${c.hazard_runs} of ${c.valid}`),
          row("customer gave up", b.abandoned, c.abandoned),
          row("turn latency p50", `${num(b.latency_ms.p50, 1)} ms`, `${num(c.latency_ms.p50, 1)} ms`),
          row("model tokens per call", num(b.tokens.per_run, 0), num(c.tokens.per_run, 0))))),
      c.tokens.total
        ? el("div", { class: "tokens" },
          el("p", { style: "margin:4px 0 2px", text: "Where the candidate's tokens go, per call:" }),
          ...comps.map((k) => el("div", {}, el("span", { text: human(k) }),
            el("i", { style: `transform:scaleX(${perRun(c.cost[k], c) / maxTok})` }),
            el("span", { text: num(perRun(c.cost[k], c), 0) }))))
        : el("p", { style: "margin-top:12px;color:var(--muted)", text: "Neither version calls a model, so there is no token cost to split." }))));
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
  const readout = (n, label, bad) => el("div", { class: bad && n > 0 ? "bad" : "" }, el("b", { text: n }), el("span", { text: label }));
  stage.append(el("div", { class: "report" },
    el("section", {}, el("h2", { text: "Replay against a changed build" }),
      el("p", { text: `Every call recorded with ${nice(reg.recorded_version)} was replayed against ${nice(reg.changed_version)}. The replay serves each recorded tool answer and stops at the first step where the new build asks for something different.` })),
    el("section", { class: "readouts" },
      readout(reg.replayed, "calls replayed"),
      readout(reg.diverged, "stopped at a changed step"),
      readout(reg.lost_success, "lost the goal when run on live", true),
      readout(reg.new_hazards, "new hazard when run on live", true)),
    c ? el("section", {},
      el("h2", { text: `One of them: ${c.scenario}, step ${c.step}` }),
      el("p", {}, "Recorded: ", el("code", { text: call(c.expected, "no further call, the recorded run ended here") })),
      el("p", {}, "New build: ", el("code", { text: call(c.got, "no call") })),
      el("p", { text: `Served up to that step and run live after it, the call went from ${c.success_before ? "goal met" : "goal not met"} to ${c.success_after ? "goal met" : "goal not met"}${c.hazards_after.length ? `, with hazard ${c.hazards_after.map(human).join(", ")}` : ""}.` }),
      el("button", { type: "button", class: "btn", onclick: () => openTranscript(c.scenario, "The call as recorded before the change.", reg.recorded_turns), text: "Read the recorded call" })) : null));
}

// ---------------------------------------------------------------- adversarial view

function renderAttacks(stage) {
  const d = state.data;
  const atts = d.attacks;
  const cand = d.comparison.candidate;
  const hz = atts.filter((a) => a.candidate_hazards.length).length;
  const planted = sum(atts.map((a) => a.planted_calls.length));
  const lines = [`${atts.length} adversarial personas from the customers on this page, replayed on ${nice(cand)}.`];
  if (planted) {
    const res = sum(atts.map((a) => a.blocked_by_resolver || 0));
    const srv = sum(atts.map((a) => a.blocked_by_server || 0));
    lines.push(`They tried ${planted} planted tool calls. The agent's resolver refused ${res} before sending, and Warden's server refused ${srv}.`);
  }
  lines.push(hz ? `${hz} still caused a hazard.` : "None caused a hazard.");
  stage.append(el("p", { class: "summary", text: lines.join(" ") }));
  stage.append(el("div", { class: "attacks" }, atts.map((a) => {
    const bad = a.candidate_hazards.length > 0;
    const chips = [
      ...a.planted_calls.map((t) => el("span", { class: "chip", text: t })),
      ...a.candidate_hazards.map((h) => el("span", { class: "chip bad", text: human(h) })),
    ];
    return el("button", { type: "button", class: "attack", onclick: () => openTranscript(a.id, `${cap(human(a.kind))} on ${nice(cand)}`, a.turns) },
      el("div", {}, el("strong", { text: a.kind ? cap(human(a.kind)) : "Planted in a tool result" }),
        el("q", { text: a.lines.length ? a.lines[0] : "Planted in the tool results, not said by the customer." }),
        chips.length ? el("div", { class: "chips" }, chips) : null),
      el("span", { class: `attack__state${bad ? " bad" : ""}` },
        el("span", { class: `lamp ${bad ? "hold" : "pass"}`, "aria-hidden": "true" }, el("i")), bad ? "got through" : "blocked"));
  })));
}

boot().catch((e) => {
  const stage = $("#stage");
  stage.removeAttribute("aria-busy");
  stage.replaceChildren(el("div", { class: "empty" },
    el("p", { text: `The recorded runs did not load (${e.message}). Check the connection and try again.` }),
    el("button", { type: "button", class: "btn", onclick: () => location.reload(), text: "Try again" })));
});
