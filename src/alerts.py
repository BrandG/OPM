"""Change-only alerting: turn scan results into alerts on state *transitions*.

Per symbol the actionable state is WATCHING (a setup qualifies but price hasn't
pulled back into the entry zone yet), ARMED (price is in the entry zone now —
place the bracket), or FLAT (no setup). We alert only when the state changes, or
when an armed/watching setup is replaced by a materially different one (a changed
support zone), so re-running never re-sends the same standing setup.

Pure functions; the runner (scripts/monitor.py) supplies fresh setups and the
persisted prior state.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# Events, roughly by urgency. ARMED and CLEARED are the ones you act on
# (place / cancel bracket orders); NEW_WATCH and DISARMED are informational.
ACTIONABLE = {"ARMED", "CLEARED"}


def setup_state(setup: Optional[dict]) -> str:
    if not setup or not setup.get("passed"):
        return "FLAT"
    return "ARMED" if setup.get("armed") else "WATCHING"


def zone_id(setup: Optional[dict]) -> Optional[str]:
    z = (setup or {}).get("support")
    return f"{z['low']:.2f}-{z['high']:.2f}" if z else None


def _record(symbol: str, state: str, setup: dict, now: str) -> dict:
    return {
        "symbol": symbol.upper(), "state": state, "zone_id": zone_id(setup),
        "side": setup.get("side", "long"),
        "entry": setup.get("entry"), "stop": setup.get("stop"),
        "target": setup.get("target"), "trade_score": setup.get("trade_score"),
        "sector": setup.get("sector", "?"), "updated_at": now,
    }


def evaluate(symbol: str, prev: Optional[dict], setup: Optional[dict], now: str
             ) -> Tuple[List[dict], Optional[dict]]:
    """Return (events, new_state_record). new_state_record is None if the symbol
    should be cleared from the state store (went FLAT)."""
    prev_state = prev["state"] if prev else "FLAT"
    prev_zone = prev["zone_id"] if prev else None
    cur_state = setup_state(setup)
    cur_zone = zone_id(setup)

    def event(kind: str) -> dict:
        base = {"symbol": symbol.upper(), "event": kind, "to_state": cur_state,
                "from_state": prev_state}
        if setup:
            base.update({k: setup.get(k) for k in
                         ("side", "price", "entry", "stop", "target", "rr",
                          "corridor_pct", "trade_score", "sector")})
        return base

    if cur_state == "FLAT":
        events = [event("CLEARED")] if prev_state != "FLAT" else []
        return events, None

    changed = (prev_state == "FLAT") or (cur_zone != prev_zone)
    events: List[dict] = []
    if cur_state == "ARMED" and (prev_state != "ARMED" or changed):
        events.append(event("ARMED"))
    elif cur_state == "WATCHING" and (prev_state == "FLAT" or changed):
        events.append(event("NEW_WATCH"))
    elif cur_state == "WATCHING" and prev_state == "ARMED":
        events.append(event("DISARMED"))
    # WATCHING->WATCHING or ARMED->ARMED with the same zone => no event (no spam).

    return events, _record(symbol, cur_state, setup, now)


def format_event(e: dict) -> str:
    sym, kind = e["symbol"], e["event"]
    if kind == "CLEARED":
        return f"  CLEARED   {sym:<6} setup gone / invalidated — cancel any resting order"
    side = (e.get("side") or "long").upper()
    money = (f"entry {e['entry']:.2f}  stop {e['stop']:.2f}  target {e['target']:.2f}  "
             f"R/R {e['rr']:.1f}  score {e['trade_score']:.0f}  [{e.get('sector','?')}]")
    if kind == "ARMED":
        return f"  ARMED *   {sym:<6} {side}  {money}"
    if kind == "NEW_WATCH":
        return f"  watching  {sym:<6} {side}  {money}"
    if kind == "DISARMED":
        return f"  disarmed  {sym:<6} price left the entry zone"
    return f"  {kind:<9} {sym}"
