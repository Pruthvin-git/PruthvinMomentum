#!/usr/bin/env python3
"""
K-5 bi-weekly Friday mail — Alpha 50, Microcap 250, Midcap Momentum 50.

One email, three books. Same engine as the Alpha live analog:
  21-day ROC dual momentum (ROC > 0), equal-weight Top-5.
  Rebalance on even W-FRI Fridays. BUY / SELL vs the previous fortnight.

Scheduled: Friday 20:30 IST. Odd-week Fridays exit 0 unless --force.

Usage:
  python k5_2w_combined_mail.py --no-email --force
  python k5_2w_combined_mail.py
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
IDEA = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(IDEA / "Hourly_Momentum"))

from email_util import send_email  # noqa: E402
from smtp_env import load_smtp_env  # noqa: E402

from backtest_core import dual_top_k, is_biweekly_friday, wfri_even  # noqa: E402
from run_microcap_topk_years import MC_CSV, load_microcap_symbols  # noqa: E402
from run_topn_grid import UNIVERSE_CSV, close_matrix, download_closes, load_symbols, yf_symbol  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_EMAIL_TO = "pruthvin98@gmail.com"
K = 5
LOOKBACK = 21
OUT = ROOT / "daily_output"
LOG_DIR = ROOT / "logs"

BASKETS = (
    {
        "key": "alpha50",
        "title": "Alpha 50",
        "short": "A",
        "strategy": "alpha50|lb21|top5|2W|dual",
        "csv": UNIVERSE_CSV["alpha50"],
        "sheet": "Alpha",
    },
    {
        "key": "microcap250",
        "title": "Microcap 250",
        "short": "MC",
        "strategy": "microcap250|lb21|top5|2W|dual",
        "csv": MC_CSV,
        "sheet": "Micro",
    },
    {
        "key": "momentum50",
        "title": "Midcap Momentum 50",
        "short": "MM",
        "strategy": "momentum50|lb21|top5|2W|dual",
        "csv": UNIVERSE_CSV["momentum50"],
        "sheet": "MidMom",
    },
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
log = logging.getLogger("k5_2w_mail")


def last_trading_day(on: date | None = None) -> date:
    d = on or datetime.now(IST).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def load_basket_symbols(key: str, csv_path: Path) -> list[str]:
    if key == "microcap250":
        return load_microcap_symbols()
    return load_symbols(csv_path)


def load_names(csv_path: Path) -> dict[str, str]:
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


def biweekly_friday_bars(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    return [ts for ts in index if int(ts.weekday()) == 4 and wfri_even(ts)]


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
                "roc21_pct": round(float(roc) * 100, 2) if pd.notna(roc) else None,
                "close": round(float(px), 2) if pd.notna(px) else None,
            }
        )
    out.sort(key=lambda r: r["roc21_pct"] if r["roc21_pct"] is not None else -999, reverse=True)
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

    fridays = biweekly_friday_bars(close.index)
    last_n = pd.Timestamp(last).normalize()
    prev_ts = next((ts for ts in reversed(fridays) if pd.Timestamp(ts).normalize() < last_n), None)

    prev_hold: list[str] = []
    if prev_ts is not None and prev_ts in live_score.index:
        prev_hold = dual_top_k(close.loc[prev_ts], live_score.loc[prev_ts], K, min_score=0.0)

    hold_set, prev_set = set(hold), set(prev_hold)
    buys = [s for s in hold if s not in prev_set]
    sells = [s for s in prev_hold if s not in hold_set]

    hold_rows = rows_for(hold, close, live_score, last, "HOLD")
    for i, r in enumerate(hold_rows, 1):
        r["rank"] = i
    return {
        "session": str(pd.Timestamp(last).date()),
        "rebal": str(pd.Timestamp(last).date()),
        "prev_rebal": str(pd.Timestamp(prev_ts).date()) if prev_ts is not None else "n/a",
        "hold": hold_rows,
        "buys": rows_for(buys, close, live_score, last, "BUY"),
        "sells": rows_for(sells, close, live_score, prev_ts if prev_ts is not None else last, "SELL"),
        "n_names": close.shape[1],
    }


def log_basket(title: str, state: dict) -> None:
    log.info(
        "%s session=%s rebal=%s prev=%s B=%d S=%d HOLD=%d names=%d",
        title,
        state["session"],
        state["rebal"],
        state["prev_rebal"],
        len(state["buys"]),
        len(state["sells"]),
        len(state["hold"]),
        state["n_names"],
    )
    for r in state["buys"]:
        log.info("  BUY  %-12s ROC21=%s close=%s", r["symbol"], r["roc21_pct"], r["close"])
    for r in state["sells"]:
        log.info("  SELL %-12s ROC21=%s close=%s", r["symbol"], r["roc21_pct"], r["close"])
    for r in state["hold"]:
        log.info("  HOLD #%s %-12s ROC21=%s close=%s", r["rank"], r["symbol"], r["roc21_pct"], r["close"])


def basket_html(title: str, strategy: str, state: dict) -> list[str]:
    return [
        f"<h2>{title}</h2>",
        f"<p><code>{strategy}</code> | names with data: <b>{state['n_names']}</b> | "
        f"Session: <b>{state['session']}</b> | This rebalance: <b>{state['rebal']}</b> | "
        f"Previous: <b>{state['prev_rebal']}</b></p>",
        f"<p>BUY {len(state['buys'])} / SELL {len(state['sells'])} / HOLD {len(state['hold'])}</p>",
        "<h3>BUY (entered Top-5 this fortnight)</h3>",
        _table(state["buys"], ["side", "symbol", "name", "roc21_pct", "close"]),
        "<h3>SELL (left Top-5 this fortnight)</h3>",
        _table(state["sells"], ["side", "symbol", "name", "roc21_pct", "close"]),
        "<h3>HOLD — current Top-5 book</h3>",
        _table(state["hold"], ["rank", "symbol", "name", "roc21_pct", "close"]),
    ]


def build_html(results: list[tuple[dict, dict]]) -> str:
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    session = results[0][1]["session"] if results else ""
    parts = [
        "<html><body>",
        "<h2>K-5 bi-weekly — Alpha / Microcap / Midcap Momentum</h2>",
        f"<p>{stamp}</p>",
        "<p><b>Strategy:</b> 21-day ROC, long only if ROC&gt;0, equal-weight top "
        f"<b>{K}</b> in each universe. Rebalance every other Friday (even W-FRI week). "
        "Act next session (typically Monday open).</p>",
        f"<p>Session: <b>{session}</b></p>",
    ]
    for spec, state in results:
        parts.extend(basket_html(spec["title"], spec["strategy"], state))
        parts.append("<hr>")
    parts.append(
        "<p style='color:#666;font-size:12px'>"
        "Equal-weight Top-5 per book — you size. "
        "Mail is Friday 20:30 IST on even W-FRI weeks only. "
        "One email covers Alpha 50, Microcap 250, and Midcap Momentum 50.</p>"
    )
    parts.append("</body></html>")
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


def write_xlsx(path: Path, results: list[tuple[dict, dict]]) -> None:
    meta_rows = []
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        for spec, state in results:
            meta_rows.extend(
                [
                    {"basket": spec["key"], "key": "strategy", "value": spec["strategy"]},
                    {"basket": spec["key"], "key": "session", "value": state["session"]},
                    {"basket": spec["key"], "key": "rebal", "value": state["rebal"]},
                    {"basket": spec["key"], "key": "prev_rebal", "value": state["prev_rebal"]},
                    {"basket": spec["key"], "key": "buy", "value": len(state["buys"])},
                    {"basket": spec["key"], "key": "sell", "value": len(state["sells"])},
                    {"basket": spec["key"], "key": "hold", "value": len(state["hold"])},
                    {"basket": spec["key"], "key": "names", "value": state["n_names"]},
                ]
            )
            prefix = spec["sheet"]
            pd.DataFrame(state["buys"]).to_excel(xl, sheet_name=f"{prefix}_BUY", index=False)
            pd.DataFrame(state["sells"]).to_excel(xl, sheet_name=f"{prefix}_SELL", index=False)
            pd.DataFrame(state["hold"]).to_excel(xl, sheet_name=f"{prefix}_HOLD", index=False)
        pd.DataFrame(meta_rows).to_excel(xl, sheet_name="meta", index=False)


def main() -> int:
    p = argparse.ArgumentParser(description="K-5 bi-weekly Friday mail: Alpha + Microcap + Midcap Momentum")
    p.add_argument("--date", default="")
    p.add_argument("--email-to", default=os.environ.get("HOURLY_MOM_EMAIL_TO", DEFAULT_EMAIL_TO))
    p.add_argument("--no-email", action="store_true")
    p.add_argument("--force", action="store_true", help="Send even if today is not an even-week Friday")
    args = p.parse_args()

    now = datetime.now(IST)
    today = now.date()
    if not args.force:
        if today.weekday() != 4:
            log.info("Not Friday (%s) — skip. Use --force to override.", now.strftime("%A"))
            return 0
        if not is_biweekly_friday(today):
            log.info("Odd-week Friday %s — skip (next even W-FRI Friday). Use --force to override.", today)
            return 0

    session = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else last_trading_day()
    OUT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    baskets: list[tuple[dict, list[str], dict[str, str]]] = []
    all_syms: list[str] = []
    for spec in BASKETS:
        csv_path = Path(spec["csv"])
        if not csv_path.exists():
            log.error("Universe CSV missing for %s: %s", spec["key"], csv_path)
            return 1
        symbols = load_basket_symbols(spec["key"], csv_path)
        names = load_names(csv_path)
        baskets.append((spec, symbols, names))
        all_syms.extend(symbols)

    uniq = sorted(set(all_syms))
    warm = (pd.Timestamp(session) - pd.DateOffset(days=400)).strftime("%Y-%m-%d")
    log.info("Baskets=%d union=%d session=%s", len(baskets), len(uniq), session)
    ohlcv = download_closes(uniq, warm, str(session))

    results: list[tuple[dict, dict]] = []
    for spec, symbols, names in baskets:
        close = close_matrix(ohlcv, symbols)
        if close.empty or close.shape[1] < K:
            log.error("Not enough daily data for %s: %s", spec["key"], close.shape)
            return 1
        state = build_state(close, session)
        state["hold"] = attach_names(state["hold"], names)
        state["buys"] = attach_names(state["buys"], names)
        state["sells"] = attach_names(state["sells"], names)
        log_basket(spec["title"], state)
        results.append((spec, state))

    stamp = datetime.now(IST).strftime("%Y%m%d_%H%M")
    session_s = results[0][1]["session"]
    out_xlsx = OUT / f"k5_2w_{session_s}_{stamp}.xlsx"
    try:
        write_xlsx(out_xlsx, results)
        log.info("Saved %s", out_xlsx)
        _sync_hub_books()
    except Exception as e:
        log.warning("xlsx skipped: %s", e)

    bits = [f"{spec['short']} B{len(st['buys'])}/S{len(st['sells'])}" for spec, st in results]
    subject = f"K5 2W | {session_s} | " + " | ".join(bits)
    html = build_html(results)
    if not args.no_email:
        send_mail(args.email_to, subject, html)
    else:
        log.info("Subject: %s", subject)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
