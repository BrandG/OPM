from src.alerts import setup_state, zone_id, evaluate


def _setup(passed=True, armed=False, sup=(95, 96), **extra):
    s = {"passed": passed, "armed": armed, "side": "long",
         "support": {"low": sup[0], "high": sup[1]}, "entry": 96.1, "stop": 94.3,
         "target": 110.0, "rr": 5.0, "corridor_pct": 0.1, "trade_score": 70.0,
         "sector": "Industrials", "price": 97.0}
    s.update(extra)
    return s


def test_state_mapping():
    assert setup_state(None) == "FLAT"
    assert setup_state(_setup(passed=False)) == "FLAT"
    assert setup_state(_setup(armed=False)) == "WATCHING"
    assert setup_state(_setup(armed=True)) == "ARMED"


def test_new_watch_then_arm_then_no_spam():
    # FLAT -> WATCHING
    ev, rec = evaluate("XYZ", None, _setup(armed=False), "t1")
    assert [e["event"] for e in ev] == ["NEW_WATCH"] and rec["state"] == "WATCHING"

    # WATCHING -> ARMED
    ev2, rec2 = evaluate("XYZ", rec, _setup(armed=True), "t2")
    assert [e["event"] for e in ev2] == ["ARMED"]

    # ARMED -> ARMED (same zone): no repeat alert
    ev3, rec3 = evaluate("XYZ", rec2, _setup(armed=True), "t3")
    assert ev3 == []


def test_changed_zone_realerts():
    _, rec = evaluate("XYZ", None, _setup(armed=True), "t1")
    # Same ARMED state but a different support zone -> treat as a new setup.
    ev, _ = evaluate("XYZ", rec, _setup(armed=True, sup=(80, 81)), "t2")
    assert [e["event"] for e in ev] == ["ARMED"]


def test_disarm_and_clear():
    _, armed = evaluate("XYZ", None, _setup(armed=True), "t1")
    ev, rec = evaluate("XYZ", armed, _setup(armed=False), "t2")     # ARMED -> WATCHING
    assert [e["event"] for e in ev] == ["DISARMED"]
    ev2, rec2 = evaluate("XYZ", rec, None, "t3")                    # -> FLAT
    assert [e["event"] for e in ev2] == ["CLEARED"] and rec2 is None


def test_flat_to_flat_is_silent():
    ev, rec = evaluate("XYZ", None, None, "t1")
    assert ev == [] and rec is None
