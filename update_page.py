#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from pathlib import Path
import os, re, sys, time
from datetime import datetime
import requests
import pandas as pd

# ============================== Config ========================================

# Default SVG source (Wikimedia “Blank map of the United States, territories not included”)
DEFAULT_SVG_URL = ("https://upload.wikimedia.org/wikipedia/commons/1/1a/"
                   "Blank_US_Map_%28states_only%29.svg")

# Abbrev → full state name
STATE_ABBR = {
    'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California','CO':'Colorado',
    'CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia','HI':'Hawaii','ID':'Idaho',
    'IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas','KY':'Kentucky','LA':'Louisiana',
    'ME':'Maine','MD':'Maryland','MA':'Massachusetts','MI':'Michigan','MN':'Minnesota','MS':'Mississippi',
    'MO':'Missouri','MT':'Montana','NE':'Nebraska','NV':'Nevada','NH':'New Hampshire','NJ':'New Jersey',
    'NM':'New Mexico','NY':'New York','NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma',
    'OR':'Oregon','PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina','SD':'South Dakota',
    'TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont','VA':'Virginia','WA':'Washington',
    'WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming','DC':'District of Columbia'
}

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# CSS injected into the SVG (kept minimal; page stylesheet can add more)
CSS_SNIPPET = """
/* === Added by build_map.py (no-JS choropleth) === */
.state path{stroke:#FFFFFF;stroke-width:1;transition:fill .2s ease, stroke .2s ease}
.state path:hover{stroke:#0a3f36;stroke-width:1.5}
.c0{fill:#e8ecea}
.c1{fill:#d6efe3}
.c2{fill:#bde4d6}
.c3{fill:#9fd6c5}
.c4{fill:#7cc5b1}
.c5{fill:#55b29a}
"""

# Optional markers in your HTML
MARKER_START = r"<!--\s*MAP_SVG_START\s*-->"
MARKER_END   = r"<!--\s*MAP_SVG_END\s*-->"


# ============================== Helpers =======================================

def series_id_for_state(abbr: str, seasonal: str) -> str:
    return f"{abbr.upper()}UR" if seasonal.upper() == "SA" else f"{abbr.upper()}URN"

def fetch_latest_rates(seasonal: str = "SA", api_key: str | None = None, timeout=20) -> pd.DataFrame:
    api_key = api_key or os.environ.get("FRED_API_KEY")
    if not api_key:
        print("ERROR: set FRED_API_KEY or pass --key", file=sys.stderr)
        sys.exit(1)

    rows = []
    for abbr in STATE_ABBR.keys():
        sid = series_id_for_state(abbr, seasonal)
        params = {"series_id": sid, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": 1}
        try:
            r = requests.get(FRED_BASE, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            obs = (data.get("observations") or [])
            if obs:
                o = obs[0]
                date = pd.to_datetime(o.get("date"), errors="coerce")
                val = o.get("value")
                rate = float(val) if val not in ("", ".", None) else float("nan")
                rows.append({"state": abbr, "date": date, "rate": rate})
            else:
                rows.append({"state": abbr, "date": pd.NaT, "rate": float("nan")})
        except Exception as e:
            print(f"Warn: {abbr} fetch failed: {e}", file=sys.stderr)
            rows.append({"state": abbr, "date": pd.NaT, "rate": float("nan")})
        time.sleep(0.08)  # be gentle to FRED
    return pd.DataFrame(rows).sort_values("state")

def pct(x):
    return f"{x:.1f}%" if pd.notnull(x) else "—"

def quantile_bins(s: pd.Series):
    s = s.dropna()
    qs = s.quantile([0.2,0.4,0.6,0.8]).tolist() if len(s) >= 5 else [s.min(), s.min(), s.mean(), s.max()]
    q1,q2,q3,q4 = qs
    def cls(v):
        if pd.isna(v): return "c0"
        if v <= q1: return "c1"
        if v <= q2: return "c2"
        if v <= q3: return "c3"
        if v <= q4: return "c4"
        return "c5"
    return cls, (s.min(), q1, q2, q3, q4, s.max())

def ensure_svg(svg_path: Path, url: str) -> str:
    """Return SVG text, downloading if svg_path doesn't exist."""
    if svg_path.exists():
        return svg_path.read_text(encoding="utf-8")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading base SVG to {svg_path} …")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    svg_text = r.text
    # Some versions don’t tag the <g> with class="state". If missing, wrap paths in a group.
    if 'class="state"' not in svg_text:
        # Try to add class to the main group that holds paths
        svg_text = re.sub(r'<g[^>]*>', lambda m: m.group(0).replace("<g", '<g class="state"', 1) if "class=" not in m.group(0) else m.group(0), svg_text, count=1)
        if 'class="state"' not in svg_text:
            # Fallback: wrap all paths
            svg_text = re.sub(r'(<svg[^>]*>)', r'\1\n<g class="state">', svg_text, count=1)
            svg_text = re.sub(r'(</svg>)', r'</g>\n\1', svg_text, count=1)
    svg_path.write_text(svg_text, encoding="utf-8")
    return svg_text

def enhance_svg(svg_text: str, latest_df: pd.DataFrame) -> str:
    """Insert color classes + data-rate + <title> into the SVG, append CSS."""
    rates = {row.state: float(row.rate) for _, row in latest_df.iterrows()}
    classify, _ = quantile_bins(latest_df["rate"])

    # Work inside <g class="state">…</g>
    g_pat = re.compile(r'(<g\s+class="state"[^>]*>)(.*?)(</g>)', re.DOTALL|re.IGNORECASE)
    m = g_pat.search(svg_text)
    if not m:
        return svg_text
    head, body, tail = m.group(1), m.group(2), m.group(3)

    def repl_path(pm):
        cls_attr = pm.group("cls")          # e.g., 'al'
        rest_cls = pm.group("rest") or ""
        abbr = cls_attr.upper()
        name = STATE_ABBR.get(abbr, abbr)
        r = rates.get(abbr)
        r_str = f"{r:.1f}" if r is not None and pd.notnull(r) else ""
        bucket = classify(r)

        full = pm.group(0)
        # add our bucket class
        full = re.sub(r'class="[^"]*"', f'class="{cls_attr}{rest_cls} {bucket}"', full, count=1)
        # add/replace data-rate
        if 'data-rate="' in full:
            full = re.sub(r'data-rate="[^"]*"', f'data-rate="{r_str}"', full, count=1)
        else:
            full = full.replace("<path", f'<path data-rate="{r_str}"', 1)
        # inject a title tooltip
        full = re.sub(
            r'(<path[^>]*>)(\s*<title>.*?</title>)?',
            rf'\1<title>{name} — {pct(r)}</title>',
            full, flags=re.DOTALL
        )
        return full

    path_pat = re.compile(
        r'<path\s+(?P<classattr>class="(?P<cls>[a-z]{2})(?P<rest>[^"]*)")(?P<attrs>[^>]*)>.*?</path>',
        re.DOTALL
    )
    body = re.sub(path_pat, repl_path, body)
    svg_text = svg_text[:m.start()] + head + body + tail + svg_text[m.end():]

    # Append our CSS into first <style> or inject into <defs>
    if re.search(r'<style[^>]*>.*?</style>', svg_text, flags=re.DOTALL|re.IGNORECASE):
        svg_text = re.sub(
            r'(<style[^>]*>)(.*?)(</style>)',
            lambda sm: sm.group(1) + sm.group(2) + CSS_SNIPPET + sm.group(3),
            svg_text, count=1, flags=re.DOTALL|re.IGNORECASE
        )
    else:
        svg_text = re.sub(
            r'(<defs[^>]*>)(.*?)</defs>',
            lambda dm: dm.group(1) + (dm.group(2) or "") + f'\n<style type="text/css">{CSS_SNIPPET}\n</style>\n</defs>',
            svg_text, count=1, flags=re.DOTALL|re.IGNORECASE
        )
        if '<style' not in svg_text:
            # absolute fallback: prepend a <style> just after <svg>
            svg_text = re.sub(
                r'(<svg[^>]*>)',
                r'\1\n<defs><style type="text/css">' + CSS_SNIPPET + r'</style></defs>',
                svg_text, count=1, flags=re.IGNORECASE
            )
    return svg_text

def replace_svg_in_html(html_text: str, new_svg: str) -> str:
    """Replace SVG in HTML either between markers or first <svg>…</svg>."""
    start = re.search(MARKER_START, html_text)
    end = re.search(MARKER_END, html_text)
    if start and end and start.end() < end.start():
        before = html_text[:start.end()]
        after  = html_text[end.start():]
        middle = re.sub(r'<svg\b.*?</svg>', '', html_text[start.end():end.start()],
                        flags=re.DOTALL|re.IGNORECASE)
        return before + "\n" + new_svg + "\n" + after
    return re.sub(r'<svg\b.*?</svg>', new_svg, html_text, count=1, flags=re.DOTALL|re.IGNORECASE)

def update_meta_in_html(html_text: str, seasonal: str, refreshed_str: str) -> str:
    sa_label = "Seasonally Adjusted" if seasonal.upper()=="SA" else "Not Seasonally Adjusted"
    html_text = re.sub(
        r'(<span[^>]+id=["\']seasonality["\'][^>]*>)(.*?)(</span>)',
        rf'\1{sa_label}\3', html_text, flags=re.DOTALL
    )
    html_text = re.sub(
        r'(<span[^>]+id=["\']refreshed["\'][^>]*>)(.*?)(</span>)',
        rf'\1Refreshed: {refreshed_str}\3', html_text, flags=re.DOTALL
    )
    return html_text


# ============================== Main ==========================================

def main(html_path: Path, svg_path: Path, seasonal: str, api_key: str | None, svg_url: str):
    seasonal = seasonal.upper()
    if seasonal not in ("SA","NSA"):
        print("seasonal must be SA or NSA", file=sys.stderr); sys.exit(2)

    # 1) Get/latest rates
    df = fetch_latest_rates(seasonal=seasonal, api_key=api_key)
    print("Latest FRED month:", pd.to_datetime(df["date"].max()).date())

    # 2) Ensure base SVG (download if missing), then enhance it
    svg_text = ensure_svg(svg_path, svg_url)
    svg_enhanced = enhance_svg(svg_text, df)

    # 3) Replace SVG inside HTML & update badges
    html_text = html_path.read_text(encoding="utf-8")
    html_updated = replace_svg_in_html(html_text, svg_enhanced)
    refreshed = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html_updated = update_meta_in_html(html_updated, seasonal, refreshed)

    # 4) Write backup then save
    backup = html_path.with_suffix(html_path.suffix + ".bak")
    backup.write_text(html_text, encoding="utf-8")
    html_path.write_text(html_updated, encoding="utf-8")
    print(f"✓ Updated {html_path} (backup at {backup})")
    if not svg_path.exists():
        svg_path.write_text(svg_text, encoding="utf-8")
    print(f"✓ SVG at {svg_path}")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build/refresh US unemployment hover map (no JS).")
    ap.add_argument("--html", required=True, help="Path to your HTML (e.g., docs/index.html)")
    ap.add_argument("--svg", default="assets/us-map.svg", help="Where to store/use the base SVG")
    ap.add_argument("--seasonal", default="SA", choices=["SA","NSA"], help="SA (default) or NSA")
    ap.add_argument("--key", default=None, help="(Optional) FRED API key (prefer env var FRED_API_KEY)")
    ap.add_argument("--svg-url", default=DEFAULT_SVG_URL, help="Alternate SVG URL (optional)")
    args = ap.parse_args()
    main(Path(args.html), Path(args.svg), args.seasonal, args.key, args.svg_url)
