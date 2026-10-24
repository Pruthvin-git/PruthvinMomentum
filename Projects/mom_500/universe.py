"""Nifty 500 universe + Yahoo tickers for mom_500."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
NIFTY500_CSV = ROOT / "ind_nifty500list.csv"

SKIP = {"GVTD.NS", "GVT&D.NS"}
YF_OVERRIDE = {
    "GVT&D": "GVT&D.NS",
    "NAM-INDIA": "NAM-INDIA.NS",
    "GMRP&UI": "GMRP&UI.NS",
    "M&M": "M&M.NS",
    "M&MFIN": "M&MFIN.NS",
    "ARE&M": "ARE&M.NS",
}


def yf_symbol(sym: str) -> str:
    s = str(sym).strip().upper()
    if s in YF_OVERRIDE:
        return YF_OVERRIDE[s]
    raw = str(sym).strip()
    if raw in YF_OVERRIDE:
        return YF_OVERRIDE[raw]
    clean = "".join(ch for ch in s if ch.isalnum() or ch in ".-&")
    return clean if clean.endswith(".NS") else f"{clean}.NS"


def load_symbols(csv_path: Path | None = None) -> list[str]:
    path = csv_path or NIFTY500_CSV
    df = pd.read_csv(path)
    col = "Symbol" if "Symbol" in df.columns else "symbol"
    out: list[str] = []
    for raw in df[col].astype(str):
        raw_s = raw.strip().upper()
        if not raw_s or raw_s.startswith("DUMMY"):
            continue
        s = yf_symbol(raw_s)
        if s and s not in SKIP:
            out.append(s)
    return sorted(set(out))


def load_names(csv_path: Path | None = None) -> dict[str, str]:
    path = csv_path or NIFTY500_CSV
    if not path.exists():
        return {}
    df = pd.read_csv(path)
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
