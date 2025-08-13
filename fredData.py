# data_fetch.py
import requests
import os
from datetime import datetime

# ==== CONFIG ====
FRED_API_KEY = os.getenv("FRED_API_KEY")  # Set this in GitHub Secrets
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
STATE_SERIES = {
    "CA": "CAINF",  # Replace with actual FRED series IDs
    "TX": "TXINF",
    "NY": "NYINF",
    # Add all states...
}

# Load SVG template
with open("us-map-template.svg", "r", encoding="utf-8") as f:
    svg_content = f.read()

# Fetch latest inflation for each state
for state, series_id in STATE_SERIES.items():
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json"
    }
    r = requests.get(FRED_BASE_URL, params=params)
    data = r.json()
    if "observations" in data and data["observations"]:
        latest = data["observations"][-1]["value"]
        svg_content = svg_content.replace(
            f'id="{state}"',
            f'id="{state}" data-inflation="{latest}%"'
        )

# Wrap SVG in HTML
html_template = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>US Inflation Map</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<h1>US Inflation by State</h1>
<div class="map-container">
{svg_content}
</div>
<div id="tooltip"></div>
<script src="tooltip.js"></script>
</body>
</html>
"""

# Save HTML
with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_template)

print(f"Map updated: {datetime.now()}")
