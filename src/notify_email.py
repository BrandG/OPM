"""Email the OPM daily digest — the actionable ARMED/CLEARED changes.

Autonomous by design: the scheduled cycle has no Claude/MCP in the loop, so it
sends over SMTP directly. Credentials are read from the ENVIRONMENT and never
stored in the repo or handled in code — set the two env vars named in config (a
Gmail *app password*, not your account password; generate one at
https://myaccount.google.com/apppasswords with 2FA on). Locally those live in
~/.config/opm.env (chmod 600), sourced by run_cycle; on Windows, set them as
user env vars for the Task Scheduler job.

Ported from Carmen's notifier (sister project). Change-only: only called when the
monitor has actionable events, so you get mail when a setup arms/clears, not a
daily "nothing happened" note.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

# target_dist_atr above this = the target is far enough that the headline R/R is
# likely illusory (won't be reached in the ~2-week hold). Flagged, not hidden.
FAR_TARGET_ATR = 12.0


def _row(a: dict) -> str:
    tatr = a.get("target_dist_atr")
    far = (tatr is not None and tatr > FAR_TARGET_ATR)
    rr = a.get("rr")
    rr_cell = (f"{rr:.1f}" if rr is not None else "—") + (" ⚠far" if far else "")
    sym_style = "font-weight:600" + (";color:#b8860b" if far else "")
    cells = [
        (a["symbol"], sym_style),
        ((a.get("side") or "long"), ""),
        (f"{a.get('entry')}", ""),
        (f"{a.get('stop')}", "color:#b00"),
        (f"{a.get('target')}", "color:#080"),
        (rr_cell, "color:#b8860b" if far else ""),
        (f"{a.get('trade_score'):.0f}" if a.get("trade_score") is not None else "—", ""),
        (a.get("sector", "?"), "color:#555"),
    ]
    tds = "".join(f"<td style='padding:6px 10px;{st}'>{v}</td>" for v, st in cells)
    return f"<tr>{tds}</tr>"


def build_digest_html(armed: List[dict], cleared: List[dict], header: str) -> str:
    """Render actionable alerts (ARMED to place, CLEARED to cancel) as a small,
    mobile-readable HTML report. Rows with a far target are flagged, not dropped."""
    th = "<th style='padding:6px 10px;text-align:left;border-bottom:2px solid #ccc'>{}</th>"
    head = "".join(th.format(h) for h in
                   ["Symbol", "Side", "Entry", "Stop", "Target", "R:R", "Score", "Sector"])
    armed_tbl = (
        f"<table style='border-collapse:collapse;width:100%;font-size:14px'>"
        f"<tr>{head}</tr>{''.join(_row(a) for a in armed)}</table>"
        if armed else "<p style='color:#666'>No newly armed setups.</p>")
    cleared_line = ""
    if cleared:
        names = ", ".join(c["symbol"] for c in cleared)
        cleared_line = (f"<p style='margin:14px 0 0'><b>Cancel resting orders "
                        f"({len(cleared)}):</b> {names}</p>")
    return (
        f"<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:660px'>"
        f"<h2 style='margin:0 0 4px'>OPM — {len(armed)} armed · {len(cleared)} cleared</h2>"
        f"<p style='color:#666;margin:0 0 14px'>{header}</p>"
        f"{armed_tbl}{cleared_line}"
        f"<p style='color:#888;font-size:12px;margin-top:16px'>Place ARMED as GTC bracket "
        f"orders before the open; ⚠far marks a target too distant to trust the R:R. Rank by "
        f"Score, size ~5 positions. Not advice — an unproven, still-forward-testing system.</p></div>")


def build_heartbeat_html(header: str, armed_now: int) -> str:
    """Tiny 'the system ran, nothing changed' note for quiet days — so silence is
    never ambiguous between 'no changes' and 'the job died'."""
    standing = (f"{armed_now} setup(s) currently armed in the universe (unchanged since "
                f"the last run — nothing new to place)." if armed_now
                else "No setups currently armed.")
    return (
        f"<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:660px'>"
        f"<h2 style='margin:0 0 4px'>OPM — daily check-in, no changes</h2>"
        f"<p style='color:#666;margin:0 0 10px'>{header}</p>"
        f"<p style='margin:0'>{standing}</p>"
        f"<p style='color:#888;font-size:12px;margin-top:14px'>Heartbeat only — the "
        f"scan ran and found no newly armed or cleared setups. You get the full digest "
        f"the moment something changes.</p></div>")


def send_report(cfg: dict, subject: str, html: str) -> str | None:
    """Send the digest via SMTP. Returns None on success, or a reason string if it
    did nothing / failed (disabled, missing creds, no recipients, SMTP error).
    NEVER raises — email must not break the monitor run."""
    e = cfg.get("email", {})
    if not e.get("enabled"):
        return "email disabled"
    user = os.environ.get(e.get("user_env", "OPM_SMTP_USER"))
    pw = os.environ.get(e.get("password_env", "OPM_SMTP_PASSWORD"))
    to = e.get("to_addrs") or []
    if not (user and pw):
        return "no SMTP credentials in env (dormant)"
    if not to:
        return "no recipients configured"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = e.get("from_addr") or user
    msg["To"] = ", ".join(to)
    msg.attach(MIMEText(html, "html"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(e.get("smtp_host", "smtp.gmail.com"),
                          e.get("smtp_port", 587), timeout=20) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.sendmail(msg["From"], to, msg.as_string())
        return None
    except Exception as ex:               # never let email break the monitor
        return f"SMTP error: {type(ex).__name__}: {ex}"
