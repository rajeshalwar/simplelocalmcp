"""A tiny MCP server: three solar tools any MCP client can call.

Run it on its own with the MCP Inspector to click the tools by hand:
    npx @modelcontextprotocol/inspector .venv/bin/python server.py

SDK note: in mcp >= 2.0 the class many tutorials call `FastMCP` is named
`MCPServer`. Same decorator API.
"""
import json
import urllib.parse
import urllib.request

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("solar")

# For each city: (latitude, longitude, rough annual output of 1 kW of panels in
# kWh). Ballpark figures in the range NREL's PVWatts reports. Hardcoded on
# purpose: no API key, nothing to fail on stage.
CITIES = {
    "amarillo":       (35.22, -101.83, 1750),
    "austin":         (30.27,  -97.74, 1600),
    "brownsville":    (25.90,  -97.50, 1500),
    "corpus christi": (27.80,  -97.40, 1550),
    "dallas":         (32.78,  -96.80, 1550),
    "el paso":        (31.76, -106.49, 1850),
    "fort worth":     (32.76,  -97.33, 1550),
    "houston":        (29.76,  -95.37, 1450),
    "lubbock":        (33.58, -101.86, 1750),
    "midland":        (32.00, -102.08, 1800),
    "san antonio":    (29.42,  -98.49, 1600),
}

COST_PER_WATT = 2.80     # typical installed price in Texas, dollars
RATE_PER_KWH = 0.15      # typical Texas retail electricity rate, dollars

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def nearest_city(lat: float, lon: float) -> str:
    """The city in CITIES closest to a point (close enough for Texas)."""
    return min(CITIES, key=lambda c: (CITIES[c][0] - lat) ** 2 + (CITIES[c][1] - lon) ** 2)


# The docstring is not just documentation: it is what the model reads to decide
# when to call the tool and what to pass. Write it for the model.
@mcp.tool()
def geocode_address(address: str) -> dict:
    """Look up a street address in Texas and find the nearest city we have
    solar data for. Call this first when the user gives an address.
    Note: this is the one tool that uses the internet (the US Census geocoder)."""
    query = urllib.parse.urlencode(
        {"address": address, "benchmark": "Public_AR_Current", "format": "json"})
    try:
        with urllib.request.urlopen(f"{CENSUS_URL}?{query}", timeout=15) as resp:
            matches = json.load(resp)["result"]["addressMatches"]
    except Exception as exc:
        # Errors are prompts: the hint tells the model what to do next.
        return {"error": f"geocoder unreachable: {exc}",
                "hint": "Tell the user the address lookup is offline and ask for their city instead."}
    if not matches:
        return {"error": f"no match for '{address}'",
                "hint": "Ask the user for the full street address, city, state and ZIP."}

    match = matches[0]
    if match["addressComponents"]["state"] != "TX":
        return {"error": f"'{match['matchedAddress']}' is not in Texas",
                "hint": "Tell the user this assistant only covers Texas."}
    lat, lon = match["coordinates"]["y"], match["coordinates"]["x"]
    return {"matched_address": match["matchedAddress"],
            "nearest_city": nearest_city(lat, lon).title()}


@mcp.tool()
def estimate_solar_production(city: str, capacity_kw: float = 7.0) -> dict:
    """Estimate how many kWh per year a solar array produces in a Texas city.
    Use a typical home size of 7 kW unless the user gives a size."""
    key = city.lower().removesuffix(", tx").removesuffix(" tx").strip()
    if key not in CITIES:
        return {"error": f"no data for '{city}'",
                "hint": "If the user gave an address, call geocode_address and use its "
                        "nearest_city. Otherwise tell them the supported cities: "
                        + ", ".join(c.title() for c in CITIES)}
    return {"city": key.title(),
            "capacity_kw": capacity_kw,
            "annual_kwh": round(CITIES[key][2] * capacity_kw)}


@mcp.tool()
def estimate_savings(annual_kwh: float, capacity_kw: float = 7.0) -> dict:
    """Turn annual solar production (kWh) into dollars saved per year, system
    cost, and payback period in years. Pass annual_kwh from
    estimate_solar_production."""
    cost = capacity_kw * 1000 * COST_PER_WATT
    savings = annual_kwh * RATE_PER_KWH
    return {"annual_savings_usd": round(savings),
            "system_cost_usd": round(cost),
            "payback_years": round(cost / savings, 1),
            "assumptions": f"${RATE_PER_KWH}/kWh, ${COST_PER_WATT}/W installed, "
                           "no tax credit (the federal credit ended after 2025)"}


if __name__ == "__main__":
    mcp.run()  # stdio: the client starts this file as a subprocess
