#!/usr/bin/env python3
"""Microcap — Nifty Microcap 250 monthly momentum mail.

Strategy (grid winner):
  microcap250|roc252|top10|M|dual
  252-trading-day ROC, dual momentum (ROC > 0), equal-weight Top-10,
  monthly rebalance (first trading session of each calendar month).

Scheduled: weekdays ~09:30 IST (see install_microcap_mail_task.ps1).
Skips other days unless --force.

Usage:
  python microcap.py --no-email --force
  powershell -File run_microcap_mail.ps1 -NoEmail -Force
  powershell -File run_microcap_mail.ps1 -Force
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
POC = ROOT.parent / "AlphaMom_TopN_POC"
HM = ROOT.parent / "Hourly_Momentum"
sys.path.insert(0, str(POC))
sys.path.insert(0, str(HM))

from backtest_core import dual_top_k  # noqa: E402
from email_util import send_email  # noqa: E402
from run_topn_grid import close_matrix, download_closes, load_symbols, yf_symbol  # noqa: E402
from smtp_env import load_smtp_env  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_EMAIL_TO = "pruthvin98@gmail.com"
UNIVERSE_CSV = ROOT / "niftymicrocap250.csv"
STRATEGY = "microcap250|roc252|top10|M|dual"
LOOKBACK = 252
K = 10
OUT = ROOT / "monthly_output"
LOG_DIR = ROOT / "logs"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("microcap")


def last_trading_day(on: date | None = None) -> date:
    d = on or datetime.now(IST).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def first_trading_day_of_month(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def is_monthly_rebalance_day(d: date) -> bool:
    return d == first_trading_day_of_month(d.year, d.month)


def previous_rebalance_day(d: date) -> date:
    if d.month == 1:
        py, pm = d.year - 1, 12
    else:
        py, pm = d.year, d.month - 1
    return first_trading_day_of_month(py, pm)


def load_names(csv_path: Path = UNIVERSE_CSV) -> dict[str, str]:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)
    col = "Symbol" if "Symbol" in df.columns else "symbol"
    name_col = "Company Name" if "Company Name" in df.columns else col
    names: dict[str, str] = {}
    for _, r in df.iterrows():
        raw = str(r[col]).strip().upper()
        if not raw or raw.startswith("DUMMY"):
            continue
        yf = yf_symbol(raw)
        nm = str(r[name_col])
        names[yf] = nm
        names[raw] = nm
        names[yf.replace(".NS", "")] = nm
    return names


def rows_for(syms: list[str], close: pd.DataFrame, score: pd.DataFrame, ts, side: str) -> list[dict]:
    out = []
    for s in syms:
        roc = score.at[ts, s] if s in score.columns and ts in score.index else None
        px = close.at[ts, s] if s in close.columns and ts in close.index else None
        out.append(
            {
                "side": side,
                "symbol": s.replace(".NS", ""),
                "yf_symbol": s,
                "roc252_pct": round(float(roc) * 100, 2) if pd.notna(roc) else None,
                "close": round(float(px), 2) if pd.notna(px) else None,
            }
        )
    out.sort(key=lambda r: r["roc252_pct"] if r["roc252_pct"] is not None else -999, reverse=True)
    return out


def attach_names(rows: list[dict], names: dict[str, str]) -> list[dict]:
    for r in rows:
        r["name"] = names.get(r.get("yf_symbol", ""), names.get(r.get("symbol", ""), ""))
    return rows


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "<p><em>None</em></p>"
    df = pd.DataFrame(rows)
    use = [c for c in cols if c in df.columns]
    return df[use].to_html(index=False, border=1)


def build_state(close: pd.DataFrame, session: date) -> dict:
    close = close.loc[: str(session)].copy()
    if close.empty:
        raise RuntimeError("no close data up to session")
    last = close.index[-1]
    live_score = close.pct_change(LOOKBACK)
    hold = dual_top_k(close.loc[last], live_score.loc[last], K, min_score=0.0)

    prev_day = previous_rebalance_day(session)
    prev_ts = close.index[close.index <= pd.Timestamp(prev_day)]
    if len(prev_ts) == 0:
        prev_ts_val = None
        prev_hold: list[str] = []
    else:
        prev_ts_val = prev_ts[-1]
        prev_hold = dual_top_k(close.loc[prev_ts_val], live_score.loc[prev_ts_val], K, min_score=0.0)

    hold_set, prev_set = set(hold), set(prev_hold)
    buys = [s for s in hold if s not in prev_set]
    sells = [s for s in prev_hold if s not in hold_set]

    hold_rows = rows_for(hold, close, live_score, last, "HOLD")
    for i, r in enumerate(hold_rows, 1):
        r["rank"] = i
    return {
        "session": str(pd.Timestamp(last).date()),
        "rebal": str(session),
        "prev_rebal": str(prev_day),
        "prev_session": str(pd.Timestamp(prev_ts_val).date()) if prev_ts_val is not None else "n/a",
        "hold": hold_rows,
        "buys": rows_for(buys, close, live_score, last, "BUY"),
        "sells": rows_for(
            sells,
            close,
            live_score,
            prev_ts_val if prev_ts_val is not None else last,
            "SELL",
        ),
        "n_names": close.shape[1],
        "target_weight_pct": round(100.0 / len(hold), 2) if hold else 0.0,
    }


def build_html(state: dict) -> str:
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    cols = ["side", "symbol", "name", "roc252_pct", "close"]
    parts = [
        "<html><body>",
        "<h2>Microcap</h2>",
        f"<p>{stamp}</p>",
        f"<p><b>Strategy:</b> <code>{STRATEGY}</code></p>",
        "<p>12-month (252-day) ROC dual momentum (long only if ROC&gt;0), equal-weight Top-10. "
        "Rebalance on the first trading session of each calendar month. "
        "Act next session (typically following day open) unless you trade at close.</p>",
        f"<p>Session close: <b>{state['session']}</b> | Rebalance month anchor: <b>{state['rebal']}</b> | "
        f"Prior month anchor: <b>{state['prev_rebal']}</b> | Names with data: <b>{state['n_names']}</b></p>",
        f"<p>BUY {len(state['buys'])} / SELL {len(state['sells'])} / HOLD {len(state['hold'])} | "
        f"Target weight each name: <b>{state['target_weight_pct']}%</b> (if fully invested)</p>",
        "<h3>BUY (new in Top-10)</h3>",
        _table(state["buys"], cols),
        "<h3>SELL (dropped from Top-10)</h3>",
        _table(state["sells"], cols),
        "<h3>HOLD — current Top-10 book</h3>",
        _table(state["hold"], ["rank"] + cols),
        "<p style='color:#666;font-size:12px'>Universe: niftymicrocap250.csv (current members). "
        "Not investment advice. Survivorship vs historical index membership applies to backtests only.</p>",
        "</body></html>",
    ]
    return "\n".join(parts)


def _sync_hub_books() -> None:
    script = ROOT.parent / "signals-hub" / "scripts" / "sync_mail_books.py"
    if script.exists():
        subprocess.run([sys.executable, str(script)], check=False)


def send_mail(to_addr: str, subject: str, html: str) -> None:
    load_smtp_env()
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    if not user or not password:
        raise RuntimeError("SMTP_USER/SMTP_PASSWORD not set — configure smtp_config.ps1")
    send_email(
        to_addr,
        subject,
        html,
        os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        int(os.environ.get("SMTP_PORT", "465")),
        user,
        password,
    )
    log.info("Email sent to %s", to_addr)


def write_xlsx(path: Path, state: dict) -> None:
    meta = pd.DataFrame(
        [
            {"key": "strategy", "value": STRATEGY},
            {"key": "session", "value": state["session"]},
            {"key": "rebal", "value": state["rebal"]},
            {"key": "prev_rebal", "value": state["prev_rebal"]},
            {"key": "buy", "value": len(state["buys"])},
            {"key": "sell", "value": len(state["sells"])},
            {"key": "hold", "value": len(state["hold"])},
            {"key": "names", "value": state["n_names"]},
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        meta.to_excel(xl, sheet_name="meta", index=False)
        pd.DataFrame(state["buys"]).to_excel(xl, sheet_name="BUY", index=False)
        pd.DataFrame(state["sells"]).to_excel(xl, sheet_name="SELL", index=False)
        pd.DataFrame(state["hold"]).to_excel(xl, sheet_name="HOLD", index=False)


def main() -> int:
    p = argparse.ArgumentParser(description="Microcap 12-month ROC Top-10 monthly mail")
    p.add_argument("--date", default="", help="Session YYYY-MM-DD (default: last trading day)")
    p.add_argument("--email-to", default=os.environ.get("HOURLY_MOM_EMAIL_TO", DEFAULT_EMAIL_TO))
    p.add_argument("--no-email", action="store_true")
    p.add_argument("--force", action="store_true", help="Send even if today is not the monthly rebalance day")
    args = p.parse_args()

    session = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else last_trading_day()
    if not args.force and not is_monthly_rebalance_day(session):
        log.info(
            "Not monthly rebalance day (%s; need first trading day of month). Use --force.",
            session,
        )
        return 0

    if not UNIVERSE_CSV.exists():
        log.error("Missing universe CSV: %s", UNIVERSE_CSV)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    symbols = load_symbols(UNIVERSE_CSV)
    names = load_names()
    warm = (pd.Timestamp(session) - pd.DateOffset(days=500)).strftime("%Y-%m-%d")
    log.info("symbols=%d session=%s warm=%s", len(symbols), session, warm)
    ohlcv = download_closes(symbols, warm, str(session))
    close = close_matrix(ohlcv, symbols)
    if close.empty or close.shape[1] < K:
        log.error("Not enough daily data: %s", close.shape)
        return 1

    state = build_state(close, session)
    state["hold"] = attach_names(state["hold"], names)
    state["buys"] = attach_names(state["buys"], names)
    state["sells"] = attach_names(state["sells"], names)

    log.info(
        "session=%s rebal=%s prev=%s B=%d S=%d HOLD=%d names=%d",
        state["session"],
        state["rebal"],
        state["prev_rebal"],
        len(state["buys"]),
        len(state["sells"]),
        len(state["hold"]),
        state["n_names"],
    )
    for r in state["hold"]:
        log.info("  HOLD #%s %-14s ROC252=%s close=%s", r["rank"], r["symbol"], r["roc252_pct"], r["close"])

    stamp = datetime.now(IST).strftime("%Y%m%d_%H%M")
    out_xlsx = OUT / f"microcap_{state['session']}_{stamp}.xlsx"
    try:
        write_xlsx(out_xlsx, state)
        _sync_hub_books()
        log.info("Saved %s", out_xlsx)
    except Exception as e:
        log.warning("xlsx skipped: %s", e)

    subject = f"Microcap | {state['session']} | B{len(state['buys'])}/S{len(state['sells'])}"
    html = build_html(state)
    if not args.no_email:
        send_mail(args.email_to, subject, html)
    else:
        log.info("Subject: %s", subject)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
