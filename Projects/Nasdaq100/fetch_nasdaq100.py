#!/usr/bin/env python3
"""Download current Nasdaq-100 constituents from the NDX quote page API."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
API = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
PAGE = "https://www.nasdaq.com/market-activity/quotes/nasdaq-ndx-index"
CSV = ROOT / "nasdaq100.csv"
META = ROOT / "nasdaq100_meta.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": PAGE,
}


def us_yf(sym: str) -> str:
    s = str(sym).strip().upper()
    return s.replace(".", "-").replace("/", "-")


def fetch_rows() -> tuple[list[dict], dict]:
    resp = requests.get(API, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    block = ((payload.get("data") or {}).get("data") or {})
    rows = block.get("rows") or []
    asof = (payload.get("data") or {}).get("date") or ""
    if not rows:
        raise RuntimeError("Nasdaq NDX API returned no rows")
    return rows, {"asof": asof, "n": len(rows), "source": API, "page": PAGE}


def constituents_frame(rows: list[dict]) -> pd.DataFrame:
    out = []
    seen: set[str] = set()
    for r in rows:
        raw = str(r.get("symbol") or "").strip().upper()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        out.append(
            {
                "Company Name": str(r.get("companyName") or "").strip(),
                "Symbol": raw,
                "yf": us_yf(raw),
                "lastSalePrice": r.get("lastSalePrice"),
                "marketCap": r.get("marketCap"),
            }
        )
    return pd.DataFrame(out).sort_values("Symbol")


def hub_rows(df: pd.DataFrame) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for _, r in df.iterrows():
        yf = str(r.get("yf") or us_yf(str(r.get("Symbol") or ""))).strip()
        if not yf or yf in seen:
            continue
        seen.add(yf)
        rows.append(
            {
                "symbol": str(r.get("Symbol") or yf).strip().upper(),
                "name": str(r.get("Company Name") or yf).strip(),
                "yf": yf,
            }
        )
    return rows


def write_universe(df: pd.DataFrame, meta: dict, hub_json: Path | None = None) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV, index=False)
    meta.update(
        {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "symbols": int(len(df)),
            "csv": str(CSV),
        }
    )
    META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if hub_json is not None:
        hub_json.parent.mkdir(parents=True, exist_ok=True)
        hub_json.write_text(json.dumps(hub_rows(df), indent=2), encoding="utf-8")


def main() -> int:
    rows, meta = fetch_rows()
    df = constituents_frame(rows)
    write_universe(df, meta)
    print(f"wrote {CSV} n={len(df)} asof={meta.get('asof')}", flush=True)
    print(",".join(df["Symbol"].tolist()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
