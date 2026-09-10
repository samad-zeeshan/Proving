"""Tables for a voice agent under transcript noise (MTVA) and under acoustic stress (TRACE)."""

from __future__ import annotations

from statistics import fmean


def _friction(run: dict) -> int:
    return sum(1 for t in run["turns"] if t.get("friction"))


def _customer_turns(run: dict) -> int:
    return sum(1 for t in run["turns"] if t.get("customer"))


def row(condition: str, runs: list[dict], reference: list[dict] | None) -> dict:
    valid = [r for r in runs if r["outcome"]["valid"]]
    words = sum(r["final_state"].get("channel", {}).get("words", 0) for r in valid)
    errors = sum(r["final_state"].get("channel", {}).get("word_errors", 0) for r in valid)
    troubled = [r for r in valid if _friction(r)]
    out = {
        "condition": condition, "runs": len(valid),
        "completed": sum(1 for r in valid if r["outcome"]["success"]),
        "wrong_actions": sum(1 for r in valid if "wrong_booking" in r["outcome"]["hazards"]
                             or "wrong_phone" in r["outcome"]["hazards"]),
        "hazard_runs": sum(1 for r in valid if r["outcome"]["hazards"]),
        "abandoned": sum(1 for r in valid if r["outcome"]["abandoned"]),
        "word_error_rate": round(errors / words, 3) if words else 0.0,
        # TRACE's recovery: of the calls where the agent hit trouble, how many still ended well.
        "troubled": len(troubled),
        "recovered": sum(1 for r in troubled if r["outcome"]["success"]),
        "customer_turns": round(fmean(_customer_turns(r) for r in valid), 2) if valid else None,
    }
    if reference is not None:
        ref = {r["scenario"]: r for r in reference if r["outcome"]["valid"]}
        both = [(r, ref[r["scenario"]]) for r in valid
                if r["scenario"] in ref and r["outcome"]["success"] and ref[r["scenario"]]["outcome"]["success"]]
        # User effort as extra caller turns, only over calls that succeeded in both arms, so a call that
        # gave up early does not look like less effort.
        out["extra_turns"] = round(fmean(_customer_turns(a) - _customer_turns(b) for a, b in both), 2) \
            if both else None
        out["paired_successes"] = len(both)
    return out
