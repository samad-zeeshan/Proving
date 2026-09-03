"""The recording proxy: record, replay, synthesize and cut-point replay."""

import pytest

from proving.toolsim import proxy as px
from proving.toolsim import trajectory


class Shop:
    """A toy backend with state, so replay and cut-point behaviour is visible."""

    def __init__(self):
        self.orders = []
        self.calls = 0

    def order(self, item):
        self.calls += 1
        if item == "ghost":
            raise KeyError("no such item")
        self.orders.append(item)
        return {"order_id": f"o-{len(self.orders)}", "item": item}


def _session(p: px.Proxy, shop: Shop, items, model=lambda i: f"say {i}"):
    out = []
    for i in items:
        out.append(p.call("model", "plan", {"i": i}, live=lambda i=i: model(i)))
        try:
            out.append(p.call("tool", "order", {"item": i}, live=lambda i=i: shop.order(i),
                              synth=lambda i=i: {"order_id": "o-synth", "item": i}))
        except Exception as exc:  # noqa: BLE001
            out.append(f"error:{type(exc).__name__}")
    return out


def test_record_logs_every_boundary_with_a_step_index():
    shop = Shop()
    p = px.Proxy()
    _session(p, shop, ["tea", "cake"])
    assert [e.step for e in p.log] == [0, 1, 2, 3]
    assert [e.kind for e in p.log] == ["model", "tool", "model", "tool"]
    assert p.log[1].args == {"item": "tea"} and p.log[1].out == {"order_id": "o-1", "item": "tea"}
    assert p.log[1].source == "live"


def test_replay_serves_recorded_outputs_without_calling_the_backend():
    shop = Shop()
    rec = px.Proxy()
    first = _session(rec, shop, ["tea", "cake"])
    fresh = Shop()
    rep = px.Proxy(replay=rec.log)
    again = _session(rep, fresh, ["tea", "cake"], model=lambda i: pytest.fail("model called in replay"))
    rep.finish()
    assert again == first
    assert fresh.calls == 0
    assert {e.source for e in rep.log} == {"served"}


def test_replay_reports_divergence_at_the_step():
    rec = px.Proxy()
    _session(rec, Shop(), ["tea", "cake"])
    rep = px.Proxy(replay=rec.log)
    with pytest.raises(px.ReplayDivergence) as err:
        _session(rep, Shop(), ["tea", "pie"])
    # The model call for the second item is the first boundary that differs.
    assert err.value.step == 2
    assert err.value.expected["args"] == {"i": "cake"}
    assert err.value.got["args"] == {"i": "pie"}


def test_replay_reports_extra_and_missing_calls():
    rec = px.Proxy()
    _session(rec, Shop(), ["tea"])
    extra = px.Proxy(replay=rec.log)
    with pytest.raises(px.ReplayDivergence, match="beyond the record"):
        _session(extra, Shop(), ["tea", "cake"])
    short = px.Proxy(replay=rec.log)
    short.call("model", "plan", {"i": "tea"}, live=lambda: None)
    with pytest.raises(px.ReplayDivergence, match="never made"):
        short.finish()


def test_errors_are_recorded_and_raised_again_on_replay():
    rec = px.Proxy()
    out = _session(rec, Shop(), ["ghost"])
    assert out[-1] == "error:KeyError"
    assert rec.log[1].error["type"].endswith("KeyError")
    factory = px.ErrorFactory({"builtins.KeyError": KeyError})
    rep = px.Proxy(replay=rec.log, errors=factory)
    assert _session(rep, Shop(), ["ghost"])[-1] == "error:KeyError"
    unknown = px.Proxy(replay=rec.log)
    assert _session(unknown, Shop(), ["ghost"])[-1] == "error:RecordedError"


def test_synthesize_uses_the_rules_backend_for_tools_only():
    shop = Shop()
    p = px.Proxy(backend="synth")
    out = _session(p, shop, ["tea"])
    assert out == ["say tea", {"order_id": "o-synth", "item": "tea"}]
    assert shop.calls == 0
    assert p.log[1].source == "synth"
    with pytest.raises(px.NoSynthesizer):
        p.call("tool", "refund", {}, live=lambda: None)


def test_cut_point_serves_before_k_and_runs_live_after():
    shop = Shop()
    rec = px.Proxy()
    _session(rec, shop, ["tea", "cake", "pie"])
    live = Shop()
    cut = px.Proxy(replay=rec.log, cut=3)
    out = _session(cut, live, ["tea", "cake", "scone"], model=lambda i: f"new {i}")
    cut.finish()
    # Steps 0..2 came from the record. Step 3 onward is the new code, live.
    assert [e.source for e in cut.log] == ["served", "served", "served", "live", "live", "live"]
    assert out[2] == "say cake" and out[4] == "new scone"
    # Served tool steps still ran against the backend, so its state is right after the cut.
    assert live.orders == ["tea", "cake", "scone"]


def test_cut_point_flags_a_backend_that_disagrees_with_the_record():
    rec = px.Proxy()
    _session(rec, Shop(), ["tea"])
    other = Shop()
    other.orders.append("x")  # the next order id will not match the record
    cut = px.Proxy(replay=rec.log, cut=2)
    _session(cut, other, ["tea"])
    assert cut.log[1].meta.get("sync_mismatch") is True
    assert cut.sync_mismatches == 1


def test_served_outputs_are_copies():
    rec = px.Proxy()
    _session(rec, Shop(), ["tea"])
    rep = px.Proxy(replay=rec.log)
    rep.call("model", "plan", {"i": "tea"}, live=lambda: None)
    got = rep.call("tool", "order", {"item": "tea"}, live=lambda: None)
    got["item"] = "changed"
    assert rec.log[1].out["item"] == "tea"


def test_trajectory_file_round_trip(tmp_path):
    rec = px.Proxy()
    _session(rec, Shop(), ["tea", "ghost"])
    runs = [{"scenario": "s1", "version": "v", "steps": [e.to_dict() for e in rec.log]}]
    path = tmp_path / "runs.jsonl.gz"
    trajectory.write_runs(path, runs)
    back = trajectory.read_runs(path)
    assert back == runs
    steps = [px.Envelope.from_dict(d) for d in back[0]["steps"]]
    assert steps == rec.log


def test_annotated_meta_is_kept_and_served():
    rec = px.Proxy()
    got = rec.call("model", "nlu", {"u": "hi"}, live=lambda: px.Annotated("ok", {"usage": {"prompt_tokens": 9}}))
    assert got == "ok" and rec.log[0].meta["usage"] == {"prompt_tokens": 9}
    rep = px.Proxy(replay=rec.log)
    assert rep.call("model", "nlu", {"u": "hi"}, live=lambda: None) == "ok"
    assert rep.log[0].meta["usage"] == {"prompt_tokens": 9}


def test_divergence_is_remembered_even_if_swallowed():
    rec = px.Proxy()
    _session(rec, Shop(), ["tea"])
    rep = px.Proxy(replay=rec.log)
    try:
        rep.call("model", "plan", {"i": "other"}, live=lambda: None)
    except px.ReplayDivergence:
        pass
    assert rep.diverged is not None and rep.diverged.step == 0
