"""Command line: generate scenarios, simulate, compare versions, replay, report.

This file is where adapters are loaded by name. Nothing else in the core imports one.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import sys
import time
from pathlib import Path

from . import store
from .scenarios import generator, schema

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "scenarios"


def _adapter(name: str):
    from . import adapters

    return adapters.load(name)


@functools.lru_cache(maxsize=None)
def _load_all(client: str) -> tuple[schema.Scenario, ...]:
    return tuple(schema.load_dir(SCENARIOS / client / "generated"))


def scenario_set(client: str, which: str = "all") -> list[schema.Scenario]:
    loaded = list(_load_all(client))
    if which == "all":
        return loaded
    if which == "smoke":
        return generator.smoke_set(loaded, 20)
    if which == "adversarial":
        return [s for s in loaded if s.adversarial]
    if which == "standard":
        return [s for s in loaded if not s.adversarial]
    if which == "trace":
        # Speech runs cost seconds a turn, so the acoustic pairs use four callers per template.
        return generator.smoke_set([s for s in loaded if not s.adversarial], 52)
    return [s for s in loaded if s.hypothesis == which or s.template == which or s.id == which]


def cmd_generate(args) -> int:
    adapter = _adapter(args.client)
    scenarios = generator.generate(SCENARIOS / args.client / "templates.yaml", builders=adapter.builders())
    paths = generator.write_all(scenarios, SCENARIOS / args.client / "generated")
    adversarial = sum(s.adversarial for s in scenarios)
    print(f"{args.client}: {len(paths)} scenarios ({adversarial} adversarial) from "
          f"{len({s.template for s in scenarios})} templates")
    return 0


def _summary(runs: list[dict]) -> str:
    valid = [r for r in runs if r["outcome"]["valid"]]
    ok = sum(1 for r in valid if r["outcome"]["success"])
    hazards = sum(len(r["outcome"]["hazards"]) for r in valid)
    return (f"{len(runs)} runs, {len(runs) - len(valid)} diverged, {ok}/{len(valid)} succeeded, "
            f"{hazards} hazards")


def cmd_simulate(args) -> int:
    from .runner import run_scenario
    from .scoring.deterministic import score_run

    adapter = _adapter(args.client)
    scenarios = scenario_set(args.client, args.set)
    path = Path(args.out) if args.out else store.run_path(args.client, args.version, args.set, args.customer)
    config = adapter.frozen_config(args.version)
    chk = store.Checkpoint(path)
    done = chk.done() if args.resume else {}
    if not args.resume:
        chk.partial.unlink(missing_ok=True)
    t0 = time.perf_counter()
    for i, s in enumerate(scenarios):
        if s.id in done:
            continue
        run = run_scenario(adapter, s, args.version, customer=args.customer, backend=args.backend)
        run["outcome"] = score_run(s, run)
        run["config_hash"] = store_hash(config)
        chk.add(run)
        if args.progress and (i + 1) % args.progress == 0:
            print(f"  {i + 1}/{len(scenarios)} in {time.perf_counter() - t0:.0f} s", flush=True)
    runs = chk.finish([s.id for s in scenarios])
    print(f"{args.client} {args.version} [{args.set}]: {_summary(runs)} -> {path}")
    return 0


def cmd_replay(args) -> int:
    from .runner import run_scenario
    from .scoring.deterministic import score_run, stable

    adapter = _adapter(args.client)
    by_id = {s.id: s for s in scenario_set(args.client)}
    runs = store.load_runs(Path(args.runs))
    bad = 0
    for rec in runs:
        s = by_id[rec["scenario"]]
        version = args.version or rec["version"]
        again = run_scenario(adapter, s, version, customer=rec["customer"], backend=rec["backend"],
                             replay_run=rec, cut=args.cut)
        out = score_run(s, again)
        same = stable(out) == stable(rec["outcome"])
        if again["divergence"] or (args.cut is None and not same):
            bad += 1
            where = again["divergence"]["message"] if again["divergence"] else "outcome changed"
            print(f"  {s.id}: {where[:300]}")
    print(f"replayed {len(runs)} runs of {args.runs}: {bad} diverged or changed")
    return 1 if bad else 0


def cmd_regress(args) -> int:
    """Replay saved runs against a changed build: where does it diverge, and what breaks after that step."""
    from .runner import run_scenario
    from .scoring.deterministic import score_run

    adapter = _adapter(args.client)
    by_id = {s.id: s for s in scenario_set(args.client)}
    runs = store.load_runs(Path(args.runs))
    rows = []
    for rec in runs:
        s = by_id[rec["scenario"]]
        full = run_scenario(adapter, s, args.version, backend=rec["backend"], replay_run=rec)
        row = {"scenario": s.id, "diverged": full["divergence"] is not None}
        if full["divergence"]:
            # Serve everything before the first differing step, then let the changed build run live.
            cut = run_scenario(adapter, s, args.version, backend=rec["backend"], replay_run=rec,
                               cut=full["divergence"]["step"])
            out = score_run(s, cut)
            row.update(step=full["divergence"]["step"], expected=full["divergence"]["expected"],
                       got=full["divergence"]["got"], success_before=rec["outcome"]["success"],
                       success_after=out["success"], hazards_after=out["hazards"])
        rows.append(row)
    caught = [r for r in rows if r["diverged"]]
    broke = [r for r in caught if r["success_before"] and not r["success_after"]]
    data = {"runs": args.runs.replace("\\", "/"), "recorded_version": runs[0]["version"], "changed_version": args.version,
            "replayed": len(rows), "diverged": len(caught), "lost_success": len(broke),
            "new_hazards": sum(1 for r in caught if r["hazards_after"]), "cases": caught}
    write_json(RESULTS / args.client / f"regression-{store.slug(args.version)}.json", data)
    print(f"{args.client}: {args.version} diverged on {len(caught)}/{len(rows)} recorded runs, "
          f"{len(broke)} lost their success when run on from the divergence")
    return 0 if (caught or not args.expect_caught) else 1


RESULTS = REPO / "eval" / "results"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def report_path(client: str, baseline: str, candidate: str) -> Path:
    return RESULTS / client / f"{store.slug(baseline)}-vs-{store.slug(candidate)}.json"


def cmd_report(args) -> int:
    import yaml

    from .report import build

    adapter = _adapter(args.client)
    doc = yaml.safe_load((SCENARIOS / args.client / "hypotheses.yaml").read_text(encoding="utf-8"))
    comparisons = doc["comparisons"]
    if args.baseline:
        comparisons = [c for c in comparisons if c["baseline"] == args.baseline and c["candidate"] == args.candidate]
    for comp in comparisons:
        a = store.load_runs(store.run_path(args.client, comp["baseline"]))
        b = store.load_runs(store.run_path(args.client, comp["candidate"]))
        judges_file = RESULTS / args.client / "judges.json"
        judges = json.loads(judges_file.read_text(encoding="utf-8")) if judges_file.exists() else None
        configs = {"baseline": adapter.frozen_config(comp["baseline"]),
                   "candidate": adapter.frozen_config(comp["candidate"])}
        rep = build.build(args.client, comp["baseline"], comp["candidate"], configs, doc["deployment"],
                          comp["hypotheses"], a, b, judges)
        path = report_path(args.client, comp["baseline"], comp["candidate"])
        write_json(path, rep)
        print(f"{args.client}: {comp['baseline']} vs {comp['candidate']} -> {rep['verdict_line']}")
        for h in rep["hypotheses"]:
            print(f"  {h['id']}: {h['verdict']}, improvement {h['improvement']} ({h['ci'][0]} to {h['ci'][1]})")
        if args.md:
            print(build.to_markdown(rep))
    return 0


MTVA = ["rules", "rules|noise@0.05", "rules|noise@0.1", "rules|noise@0.2", "rules|noise@0.3", "rules|split"]
TRACE = ["rules|asr@clean", "rules|asr@white@10"]


def cmd_channels(args) -> int:
    from .report import channels

    def runs_for(version: str, which: str) -> list[dict]:
        path = store.run_path(args.client, version, which)
        if not path.exists():
            if args.no_simulate:
                return []
            cmd_simulate(argparse.Namespace(client=args.client, version=version, set=which, customer="rules",
                                            backend=None, out=None, resume=False, progress=0))
        return store.load_runs(path)

    standard = [r for r in runs_for("rules", "all") if not r["adversarial"]]
    mtva = [channels.row("clean", standard, None)]
    for version in MTVA[1:]:
        mtva.append(channels.row(version.split("|")[1], runs_for(version, "standard"), standard))
    trace_ref = runs_for(TRACE[0], "trace")
    trace = [channels.row(v.split("|")[1], runs_for(v, "trace"), trace_ref if i else None)
             for i, v in enumerate(TRACE) if store.run_path(args.client, v, "trace").exists() or not args.no_simulate]
    write_json(RESULTS / args.client / "channels.json", {
        "mtva": {"set": "standard", "note": "text channel, rule parser, noise injected into caller words",
                 "rows": mtva},
        "trace": {"set": "trace", "speech": "Piper voices, faster-whisper small (Parley local-v1)",
                  "rows": trace},
    })
    for r in mtva + trace:
        print(f"  {r['condition']:>12}: {r['completed']}/{r['runs']} completed, WER {r['word_error_rate']}, "
              f"wrong actions {r['wrong_actions']}")
    return 0


def cmd_fidelity(args) -> int:
    from .runner import run_scenario
    from .scoring.deterministic import score_run

    adapter = _adapter(args.client)
    synth = {r["scenario"]: r for r in store.load_runs(store.run_path(args.client, args.version))}
    same_outcome = same_calls = 0
    differ = []
    for s in scenario_set(args.client):
        live = run_scenario(adapter, s, args.version, backend="live")
        out = score_run(s, live)
        rec = synth[s.id]
        a = (out["success"], out["hazards"], out["agent_turns"])
        b = (rec["outcome"]["success"], rec["outcome"]["hazards"], rec["outcome"]["agent_turns"])
        calls = [(st["name"], (st["error"] or {}).get("type")) for st in live["steps"] if st["kind"] == "tool"]
        rcalls = [(st["name"], (st["error"] or {}).get("type")) for st in rec["steps"] if st["kind"] == "tool"]
        same_outcome += a == b
        same_calls += calls == rcalls
        if a != b or calls != rcalls:
            differ.append(s.id)
    n = len(synth)
    write_json(RESULTS / args.client / "fidelity.json", {
        "version": args.version, "scenarios": n, "same_outcome": same_outcome, "same_tool_calls": same_calls,
        "differences": differ,
        "note": "each scenario run on the rules synthesizer and on the client's real booking service",
    })
    print(f"{args.client}: synthesizer and real service agree on {same_outcome}/{n} outcomes, "
          f"{same_calls}/{n} call sequences")
    return 0


def cmd_judge(args) -> int:
    from . import llm
    from .report import figures, judging

    runs = {v: store.load_runs(store.run_path(args.client, v)) for v in args.versions.split(",")}
    items = judging.sample(runs, args.per_version)
    cache_path = RESULTS / args.client / "judge-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    try:
        preds = judging.verdicts(items, cache, use_model=llm.enabled())
    finally:
        if cache:
            write_json(cache_path, dict(sorted(cache.items())))
    out = judging.evaluate(items, preds, llm.MODEL)
    write_json(RESULTS / args.client / "judges.json", out)
    write_text(RESULTS / args.client / "calibration.svg", figures.reliability(out["judges"]["per_judge"]))
    write_text(RESULTS / args.client / "judge-errors.svg", figures.correlation(out["judges"]["correlation"]))
    for name, j in out["judges"]["per_judge"].items():
        print(f"  {name}: accuracy {j['accuracy_raw']} -> {j['accuracy_calibrated']}, "
              f"ECE {j['ece_raw']} -> {j['ece_calibrated']}")
    corr = out["judges"]["correlation"]
    print(f"  error correlation {corr['mean_error_correlation']}, effective judges {corr['effective_judges']}")
    return 0


def store_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="proving", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="expand a client's templates into scenario files")
    g.add_argument("client")
    g.set_defaults(fn=cmd_generate)

    s = sub.add_parser("simulate", help="run a scenario set against one version and save the runs")
    s.add_argument("client")
    s.add_argument("--version", required=True)
    s.add_argument("--set", default="all", help="all, smoke, standard, adversarial, or a tag")
    s.add_argument("--customer", default="rules", choices=["rules", "llm"])
    s.add_argument("--backend", default=None, choices=["synth", "live"])
    s.add_argument("--out", default=None)
    s.add_argument("--resume", action="store_true")
    s.add_argument("--progress", type=int, default=0)
    s.set_defaults(fn=cmd_simulate)

    r = sub.add_parser("replay", help="replay saved runs, fully or from a cut point, and flag changes")
    r.add_argument("client")
    r.add_argument("--runs", required=True)
    r.add_argument("--version", default=None, help="replay against another version")
    r.add_argument("--cut", type=int, default=None)
    r.set_defaults(fn=cmd_replay)

    g2 = sub.add_parser("regress", help="replay saved runs against a changed build and show what broke")
    g2.add_argument("client")
    g2.add_argument("--runs", required=True)
    g2.add_argument("--version", required=True)
    g2.add_argument("--expect-caught", action="store_true", help="fail if nothing diverges")
    g2.set_defaults(fn=cmd_regress)

    c = sub.add_parser("channels", help="noise, split-turn and acoustic-stress tables for a voice client")
    c.add_argument("client")
    c.add_argument("--no-simulate", action="store_true", help="only summarise runs already saved")
    c.set_defaults(fn=cmd_channels)

    f = sub.add_parser("fidelity", help="compare the tool synthesizer with the client's real backend")
    f.add_argument("client")
    f.add_argument("--version", default="rules")
    f.set_defaults(fn=cmd_fidelity)

    j = sub.add_parser("judge", help="judge transcripts, calibrate against tool state, measure agreement")
    j.add_argument("client")
    j.add_argument("--versions", required=True, help="comma separated, e.g. rules,llm")
    j.add_argument("--per-version", type=int, default=120)
    j.set_defaults(fn=cmd_judge)

    p = sub.add_parser("report", help="compare two versions and write the EnterpriseVal report")
    p.add_argument("client")
    p.add_argument("--baseline", default=None)
    p.add_argument("--candidate", default=None)
    p.add_argument("--md", action="store_true", help="also print the report as Markdown")
    p.set_defaults(fn=cmd_report)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
