"""A tiny MCP server: three solar tools any MCP client can call.

Run it on its own with the MCP Inspector to click the tools by hand:
    npx @modelcontextprotocol/inspector .venv/bin/python server.py

SDK note: in mcp >= 2.0 the class many tutorials call `FastMCP` is named
`MCPServer`. Same decorator API.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("solar")

COST_PER_WATT = 2.80     # typical installed price in Texas, dollars
RATE_PER_KWH = 0.15      # typical Texas retail electricity rate, dollars

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
PVWATTS_URL = "https://developer.nlr.gov/api/pvwatts/v8.json"
# Free key from https://developer.nlr.gov/signup/. DEMO_KEY works but is
# heavily rate limited. Set it in the environment or in a .env file here.
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        name, _, value = line.strip().partition("=")
        if name and not name.startswith("#"):
            os.environ.setdefault(name, value)
NLR_API_KEY = os.environ.get("NLR_API_KEY", "DEMO_KEY")


# The docstring is not just documentation: it is what the model reads to decide
# when to call the tool and what to pass. Write it for the model.
@mcp.tool()
def geocode_address(address: str) -> dict:
    """Look up a street address in Texas and return its latitude and longitude.
    Always call this first: estimate_solar_production needs the lat and lon.
    Uses the internet (the US Census geocoder)."""
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
                "hint": "The geocoder needs a street address, not just a city. Ask the "
                        "user for the full street address, city, state and ZIP."}

    match = matches[0]
    if match["addressComponents"]["state"] != "TX":
        return {"error": f"'{match['matchedAddress']}' is not in Texas",
                "hint": "Tell the user this assistant only covers Texas."}
    return {"matched_address": match["matchedAddress"],
            "lat": round(match["coordinates"]["y"], 5),
            "lon": round(match["coordinates"]["x"], 5)}


@mcp.tool()
def estimate_solar_production(lat: float, lon: float, capacity_kw: float = 7.0) -> dict:
    """Estimate how many kWh per year a solar array produces at a location.
    Pass the lat and lon from geocode_address. Use a typical home size of 7 kW
    unless the user gives a size. Uses the internet (NLR's PVWatts)."""
    # Typical roof-mounted home system: standard panels, fixed rack, 20° tilt
    # facing south, 14% losses (the PVWatts default).
    query = urllib.parse.urlencode(
        {"api_key": NLR_API_KEY, "lat": lat, "lon": lon, "system_capacity": capacity_kw,
         "module_type": 0, "array_type": 1, "tilt": 20, "azimuth": 180, "losses": 14})
    try:
        with urllib.request.urlopen(f"{PVWATTS_URL}?{query}", timeout=30) as resp:
            data = json.load(resp)
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 422:
            data = json.load(exc)  # bad inputs: the body lists what was wrong
        else:
            return {"error": f"PVWatts unreachable: {exc}",
                    "hint": "Tell the user the solar data service is offline or rate "
                            "limited (set NLR_API_KEY for a higher limit) and to try again later."}
    if data.get("errors"):
        return {"error": "; ".join(data["errors"]),
                "hint": "Check that lat and lon came from geocode_address."}
    return {"capacity_kw": capacity_kw,
            "annual_kwh": round(data["outputs"]["ac_annual"]),
            "weather_data": data["station_info"]["weather_data_source"]}


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
