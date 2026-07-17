"""Email digest — HTML rendering, the far-target flag, and the safe-by-default guard."""

from src.notify_email import build_digest_html, send_report


def _armed(sym, entry, score=75.0, rr=4.0, tatr=3.0, sector="Industrials"):
    return {"symbol": sym, "side": "long", "event": "ARMED", "entry": entry,
            "stop": entry - 2, "target": entry + 10, "rr": rr, "trade_score": score,
            "target_dist_atr": tatr, "sector": sector}


def test_digest_html_contains_setups():
    html = build_digest_html(
        [_armed("FIX", 1760.0, score=79), _armed("HD", 338.0, score=77)],
        [{"symbol": "ABNB"}], "2026-07-14 · market UP")
    assert "OPM — 2 armed · 1 cleared" in html
    assert "FIX" in html and "HD" in html
    assert "ABNB" in html                          # cleared -> cancel line
    assert "Cancel resting orders (1)" in html


def test_digest_flags_far_target():
    # tatr 31.5 > 12 -> the illusory-R/R flag fires; a normal one does not.
    far = build_digest_html([_armed("ABT", 87.0, rr=31.5, tatr=31.5)], [], "hdr")
    near = build_digest_html([_armed("KDP", 30.0, rr=3.3, tatr=2.1)], [], "hdr")
    # "#b8860b" (gold) styles only a flagged row; the footer mentions "far" in both.
    assert "#b8860b" in far
    assert "#b8860b" not in near


def test_send_is_disabled_by_default():
    assert send_report({"email": {"enabled": False}}, "s", "<p>x</p>") == "email disabled"


def test_send_dormant_without_credentials(monkeypatch):
    monkeypatch.delenv("OPM_SMTP_USER", raising=False)
    monkeypatch.delenv("OPM_SMTP_PASSWORD", raising=False)
    cfg = {"email": {"enabled": True, "to_addrs": ["a@b.com"]}}
    assert send_report(cfg, "s", "<p>x</p>") == "no SMTP credentials in env (dormant)"


def test_send_needs_recipients(monkeypatch):
    monkeypatch.setenv("OPM_SMTP_USER", "u@x.com")
    monkeypatch.setenv("OPM_SMTP_PASSWORD", "app-pw")
    cfg = {"email": {"enabled": True, "to_addrs": []}}
    assert send_report(cfg, "s", "<p>x</p>") == "no recipients configured"
