# Flight Deal Finder — Technical Design

## The Problem

Google Flights has no public API by design — the inefficiency of manual, date-by-date, destination-by-destination searching is a feature of an ecosystem built to keep travelers slightly less informed than they could be. Airlines benefit from friction (it protects yield management), Google benefits (it drives engagement with their UI), and GDS providers benefit (they charge for data access).

This tool closes that gap. A single query — "cheapest business class from YVR to anywhere in March" — replaces what would otherwise be dozens of manual searches across destinations and date combinations. The bot programmatically sweeps all destinations and dates in one pass, ranks by price, and can monitor for drops over time.

**Origin airport defaults to YVR but is fully configurable** — users can specify any IATA airport code (e.g., SEA, BLI, SFO, LHR) as their departure point.

---

## API: Amadeus Self-Service

**Original plan was Kiwi Tequila — but their registration page is broken (blank page, Feb 2026). Amadeus turned out to be a better choice anyway:**

| Feature | Amadeus | Kiwi Tequila (unavailable) |
|---------|---------|---------------------------|
| Registration | ✅ Instant self-service | ❌ Registration broken |
| Data source | GDS (direct airline data) | Aggregator (secondhand) |
| Cabin class filter | ✅ ECONOMY / BUSINESS / FIRST | ✅ |
| "Fly Anywhere" | ✅ Flight Inspiration Search | ✅ Native |
| Python SDK | ✅ Official `amadeus` package | ❌ Manual HTTP only |
| Free tier | 500 calls/month (test env) | Unknown (can't register) |
| Price Analysis AI | ✅ Built-in historical comparison | ❌ |
| Rate limits | 10 req/sec | 100 req/min |

**ToS review (completed):** Section 3.1.1 permits free, non-exclusive use for "testing and prototyping." Free personal tool = fully compliant. No data caching beyond cache headers. Privacy policy required if end users interact with the app.

Sign up at [developers.amadeus.com/register](https://developers.amadeus.com/register)

### Key Endpoints

**1. Flight Inspiration Search** — "Where can I fly cheaply from here?"
```
GET /v1/shopping/flight-destinations?origin=YVR
```
Returns cached cheapest destinations from any origin, sorted by price. Filterable by departure date, duration, max price. This is the "anywhere" engine.

**2. Flight Offers Search** — "What's available on this specific route?"
```
GET /v2/shopping/flight-offers
  ?originLocationCode=YVR
  &destinationLocationCode=NRT
  &departureDate=2026-03-15
  &returnDate=2026-03-25
  &adults=1
  &travelClass=BUSINESS
  &max=20
  &currencyCode=CAD
```
Real-time pricing with cabin class filter. Used after Inspiration Search identifies destinations.

**3. Airport Direct Destinations** — "Where can I fly nonstop from here?"
```
GET /v1/airport/direct-destinations?departureAirportCode=YVR
```

**4. Flight Price Analysis** — "Is this a good deal?"
```
GET /v1/analytics/flight-price-analysis
  ?originIataCode=YVR
  &destinationIataCode=NRT
  &departureDate=2026-03-15
```
AI-powered comparison against historical fares. Returns whether a price is below or above average.

### Search Strategy (Two-Step)

Amadeus doesn't support "anywhere + cabin class" in a single call, so we use a two-step approach:

1. **Step 1: Discover destinations** — Flight Inspiration Search returns cheapest destinations from origin (cached, fast)
2. **Step 2: Get real-time cabin pricing** — For top N destinations, call Flight Offers Search with `travelClass=BUSINESS` and `travelClass=ECONOMY`

This is actually more accurate than a single-call approach because Step 2 uses live GDS data.

### Authentication

Amadeus uses OAuth2 (client_id + client_secret → access token). The Python SDK handles this automatically.

```python
from amadeus import Client, ResponseError

amadeus = Client(
    client_id=os.environ["AMADEUS_CLIENT_ID"],
    client_secret=os.environ["AMADEUS_CLIENT_SECRET"],
)
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│              Streamlit Web App (app.py)          │
│  (runs server-side — API keys never exposed)    │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│              Orchestrator (Python)               │
│                                                  │
│  • Accepts user input from Streamlit UI          │
│  • Step 1: Flight Inspiration Search (anywhere)  │
│  • Step 2: Flight Offers Search (per cabin)      │
│  • Filters / ranks / deduplicates results        │
│  • Computes upgrade value analysis               │
│  • Tracks price history (SQLite)                 │
│  • Rate limits user searches                     │
└────────┬───────────────────┬────────────────────┘
         │                   │
┌────────▼────────┐  ┌──────▼──────────────────┐
│   Amadeus API    │  │  Claude API (optional)   │
│  (Python SDK)    │  │  • NL query parsing      │
│                  │  │  • Deal summarization     │
│  • Inspiration   │  │  • "Should I book this?"  │
│  • Offers Search │  │                           │
│  • Price Analysis│  │                           │
└─────────────────┘  └─────────────────────────┘
```

**Security note:** Streamlit runs server-side Python. The user's browser never sees your API keys — Streamlit handles all API calls on the server and sends only rendered HTML to the client. This means **the proxy layer concern is already solved** by our architecture choice. No separate backend needed.

---

## Core Module: `flight_finder.py`

```python
import os
from amadeus import Client, ResponseError
from datetime import datetime, timedelta

# Initialize Amadeus client
amadeus = Client(
    client_id=os.environ["AMADEUS_CLIENT_ID"],
    client_secret=os.environ["AMADEUS_CLIENT_SECRET"],
)

CABIN_CLASSES = ["ECONOMY", "BUSINESS", "FIRST"]


def discover_destinations(
    origin: str = "YVR",
    departure_date: str = None,   # YYYY-MM-DD (optional)
    max_price: int = None,        # optional price cap
):
    """
    Step 1: Find cheapest destinations from origin.
    Uses cached Flight Inspiration Search (fast, broad).
    Returns list of {destination, price, departureDate, returnDate}.
    """
    params = {"origin": origin}
    if departure_date:
        params["departureDate"] = departure_date
    if max_price:
        params["maxPrice"] = max_price

    try:
        response = amadeus.shopping.flight_destinations.get(**params)
        return response.data
    except ResponseError as e:
        print(f"Inspiration search error: {e}")
        return []


def search_flights(
    origin: str = "YVR",
    destination: str = "NRT",
    departure_date: str = "2026-03-15",   # YYYY-MM-DD
    return_date: str = None,               # YYYY-MM-DD (optional)
    cabin: str = "BUSINESS",               # ECONOMY, BUSINESS, FIRST
    adults: int = 1,
    max_results: int = 10,
    currency: str = "CAD",
    nonstop: bool = False,
):
    """
    Step 2: Search for flights on a specific route with cabin class.
    Uses real-time Flight Offers Search.
    """
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": adults,
        "travelClass": cabin,
        "max": max_results,
        "currencyCode": currency,
        "nonStop": nonstop,
    }
    if return_date:
        params["returnDate"] = return_date

    try:
        response = amadeus.shopping.flight_offers_search.get(**params)
        return response.data
    except ResponseError as e:
        print(f"Flight search error for {destination}: {e}")
        return []


def search_anywhere(
    origin: str = "YVR",
    departure_date: str = None,
    return_date: str = None,
    cabins: list = None,
    top_n: int = 10,
    adults: int = 1,
    currency: str = "CAD",
):
    """
    Full "anywhere" search: discover destinations, then get
    real-time pricing per cabin class for the top N cheapest.
    """
    if cabins is None:
        cabins = ["ECONOMY", "BUSINESS"]

    # Step 1: Get cheapest destinations
    destinations = discover_destinations(origin, departure_date)
    if not destinations:
        return {}

    # Take top N destinations
    top_dests = destinations[:top_n]

    # Step 2: For each destination, search each cabin class
    all_results = {}
    for cabin in cabins:
        cabin_results = []
        for dest_info in top_dests:
            dest_code = dest_info["destination"]
            dep_date = departure_date or dest_info.get("departureDate")
            ret_date = return_date or dest_info.get("returnDate")

            flights = search_flights(
                origin=origin,
                destination=dest_code,
                departure_date=dep_date,
                return_date=ret_date,
                cabin=cabin,
                adults=adults,
                currency=currency,
            )
            if flights:
                cabin_results.extend(flights)

        # Sort by price
        cabin_results.sort(
            key=lambda f: float(f["price"]["grandTotal"])
        )
        all_results[cabin] = cabin_results

    return all_results


def get_price_analysis(origin: str, destination: str, departure_date: str):
    """
    Check if a fare is a good deal using Amadeus Price Analysis AI.
    Returns whether the price is below/above historical average.
    """
    try:
        response = amadeus.analytics.itinerary_price_metrics.get(
            originIataCode=origin,
            destinationIataCode=destination,
            departureDate=departure_date,
        )
        return response.data
    except ResponseError as e:
        print(f"Price analysis error: {e}")
        return None


def compute_upgrade_value(all_results: dict) -> list:
    """
    Compare economy vs business prices for overlapping destinations.
    Returns sorted list of upgrade comparisons (best value first).
    """
    def cheapest_by_dest(flights):
        by_dest = {}
        for f in flights:
            # Extract destination from itinerary
            segments = f["itineraries"][0]["segments"]
            dest = segments[-1]["arrival"]["iataCode"]
            price = float(f["price"]["grandTotal"])
            if dest not in by_dest or price < by_dest[dest]:
                by_dest[dest] = price
        return by_dest

    econ = cheapest_by_dest(all_results.get("ECONOMY", []))
    biz = cheapest_by_dest(all_results.get("BUSINESS", []))

    common = set(econ.keys()) & set(biz.keys())
    if not common:
        return []

    comparisons = []
    for dest in common:
        premium = biz[dest] - econ[dest]
        multiplier = biz[dest] / econ[dest] if econ[dest] > 0 else 0
        comparisons.append({
            "destination": dest,
            "economy": econ[dest],
            "business": biz[dest],
            "premium": premium,
            "multiplier": multiplier,
        })

    comparisons.sort(key=lambda x: x["multiplier"])
    return comparisons
```

---

## Streamlit Web App: `app.py`

**Why Streamlit?** Python-native, ~50 lines of UI code, free hosting on Streamlit Community Cloud, auto-deploys from GitHub. Total cost: $0. Total new languages to learn: 0.

```python
import streamlit as st
from datetime import date, timedelta
from flight_finder import search_anywhere, search_flights, compute_upgrade_value
import pandas as pd

st.set_page_config(page_title="Flight Deal Finder", page_icon="✈️", layout="wide")
st.title("✈️ Flight Deal Finder")
st.caption("Find the cheapest flights from any airport to anywhere")

# --- Rate Limiting (server-side, per session) ---
if "search_count" not in st.session_state:
    st.session_state.search_count = 0
    st.session_state.search_reset = date.today()

if st.session_state.search_reset < date.today():
    st.session_state.search_count = 0
    st.session_state.search_reset = date.today()

MAX_SEARCHES_PER_DAY = 20

# --- Sidebar: Search Parameters ---
with st.sidebar:
    st.header("Search Settings")

    fly_from = st.text_input("From (IATA code)", value="YVR",
                             help="e.g., YVR, SEA, BLI, SFO, LHR")

    col1, col2 = st.columns(2)
    with col1:
        dep_date = st.date_input("Departure date",
                                 value=date.today() + timedelta(days=30))
    with col2:
        ret_date = st.date_input("Return date",
                                 value=date.today() + timedelta(days=37))

    cabins = st.multiselect("Cabin class",
                            ["ECONOMY", "BUSINESS", "FIRST"],
                            default=["ECONOMY", "BUSINESS"])

    top_n = st.slider("Top destinations to check", 3, 20, 10,
                      help="More = better coverage but uses more API calls")

    nonstop = st.checkbox("Nonstop flights only")
    currency = st.selectbox("Currency", ["CAD", "USD", "EUR", "GBP"], index=0)

    remaining = MAX_SEARCHES_PER_DAY - st.session_state.search_count
    st.caption(f"Searches remaining today: {remaining}")

    search = st.button("🔍 Search Flights", type="primary",
                       use_container_width=True,
                       disabled=(remaining <= 0))

# --- Main: Results ---
if search:
    st.session_state.search_count += 1

    with st.spinner(f"Searching {', '.join(cabins)} from {fly_from}..."):
        results = search_anywhere(
            origin=fly_from,
            departure_date=dep_date.strftime("%Y-%m-%d"),
            return_date=ret_date.strftime("%Y-%m-%d"),
            cabins=cabins,
            top_n=top_n,
            currency=currency,
        )

    for cabin_name, flights in results.items():
        st.subheader(f"{cabin_name.title()} Class")

        if not flights:
            st.info(f"No {cabin_name.lower()} flights found.")
            continue

        rows = []
        for f in flights:
            segments = f["itineraries"][0]["segments"]
            dest = segments[-1]["arrival"]["iataCode"]
            airlines = ", ".join(set(s["carrierCode"] for s in segments))
            stops = len(segments) - 1
            duration = f["itineraries"][0].get("duration", "")

            rows.append({
                "Destination": dest,
                "Price": f"${float(f['price']['grandTotal']):,.0f} {currency}",
                "Departure": segments[0]["departure"]["at"][:10],
                "Airlines": airlines,
                "Stops": stops,
                "Duration": duration.replace("PT", "").lower(),
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

    # Upgrade value analysis
    if "ECONOMY" in results and "BUSINESS" in results:
        comparisons = compute_upgrade_value(results)
        if comparisons:
            st.subheader("💎 Upgrade Value Analysis")
            st.caption("Lower multiplier = better deal on business class")
            comp_df = pd.DataFrame([{
                "Destination": c["destination"],
                f"Economy ({currency})": f"${c['economy']:,.0f}",
                f"Business ({currency})": f"${c['business']:,.0f}",
                "Premium": f"${c['premium']:,.0f}",
                "Multiplier": f"{c['multiplier']:.1f}x",
            } for c in comparisons])
            st.dataframe(comp_df, use_container_width=True, hide_index=True)
```

**Run locally:**
```bash
streamlit run app.py
```

**Deploy to Streamlit Community Cloud (free):**
1. Push code to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Sign in with GitHub
4. Point it at your repo → `app.py`
5. Add secrets in the Secrets panel:
   ```
   AMADEUS_CLIENT_ID = "your_client_id"
   AMADEUS_CLIENT_SECRET = "your_client_secret"
   ```
6. Click Deploy → live at `https://your-username-flight-finder.streamlit.app`

---

## Privacy Policy

Required by Amadeus ToS (Section 4.3) since end users interact with the app.

```
PRIVACY POLICY — Flight Deal Finder

This is a prototype application built for personal use and portfolio demonstration.

- No user accounts are created
- No personal data is collected, stored, or shared
- No cookies are used
- No analytics or tracking are implemented
- Flight search queries are not logged
- All flight data is provided by the Amadeus API and is not cached

This application does not sell, rent, or share any user information.
Contact: [your email]
```

Save this as `PRIVACY.md` in the repo, and add a link to it in the Streamlit app footer.

---

## Rate Limiting

Rate limiting is applied at two levels:

1. **App-level (Streamlit session):** Max 20 searches per user per day, tracked via `st.session_state`. Resets daily. The search button disables when the limit is hit.

2. **API-level (Amadeus):** Amadeus enforces 10 requests/second and 500 calls/month on the test environment. The two-step search strategy uses ~(1 + N×cabins) calls per search, where N = number of destinations checked. With top_n=10 and 2 cabin classes, that's ~21 calls per search.

**Budget math:** 500 calls/month ÷ 21 calls/search ≈ 23 full searches per month on the free tier. Enough for personal use and demo purposes.

---

## How This Closes the Gap

| Manual Google Flights | This Tool |
|----------------------|-----------|
| Pick one destination at a time | Sweeps all destinations in one query |
| Check one date at a time | Covers entire date range per query |
| Check one cabin class at a time | Searches economy + business simultaneously |
| No cross-cabin comparison | Automatic upgrade value analysis |
| No historical price context | Amadeus Price Analysis AI (is this a good deal?) |
| No price alerts | Automated daily monitoring with per-cabin thresholds |
| Requires active attention | Runs passively, alerts you when deals appear |
| API key in client = security risk | Streamlit server-side = keys never exposed |

---

## Implementation Roadmap

### Phase 1: Core Search (2-3 hours)
- [ ] Install `amadeus` Python SDK
- [ ] Get `flight_finder.py` working — test Inspiration Search + Offers Search
- [ ] Verify business class results return real data

### Phase 2: Streamlit UI (2-3 hours)
- [ ] Build `app.py` with search form + results tables
- [ ] Add upgrade value analysis
- [ ] Add rate limiting via session state
- [ ] Deploy to Streamlit Community Cloud

### Phase 3: Monitoring + Alerts (1-2 hours)
- [ ] Set up `monitor.py` with SQLite price tracking
- [ ] Configure alert delivery (email or Slack)
- [ ] Deploy as GitHub Action (daily cron)

### Phase 4: Enhancements (ongoing)
- [ ] Claude NL interface for plain English queries
- [ ] Price trend visualization
- [ ] Multi-origin support (YVR + SEA + BLI comparison)
- [ ] "Deal score" via Flight Price Analysis API
- [ ] Airline preference weighting (e.g., prefer Air Canada for Aeroplan)
- [ ] Privacy policy page in Streamlit footer

---

## Dependencies

```
amadeus>=9.0
python-dotenv>=1.0
streamlit>=1.38
pandas>=2.0
```

Optional (Phase 3+):
```
anthropic>=0.40    # Claude NL interface
matplotlib         # price trend charts
```

---

## Configuration & Secrets

| Variable | Purpose | Where to store |
|----------|---------|---------------|
| `AMADEUS_CLIENT_ID` | API authentication | `.env` locally / Streamlit Secrets in prod |
| `AMADEUS_CLIENT_SECRET` | API authentication | `.env` locally / Streamlit Secrets in prod |
| `ANTHROPIC_API_KEY` | Claude NL parsing (Phase 4) | `.env` locally |
| `FLY_FROM` | Default origin airport | App UI (default: YVR) |

---

## Notes

- Amadeus dates use **YYYY-MM-DD** format (ISO 8601), not DD/MM/YYYY
- Flight Inspiration Search uses cached data (updated daily) — good for discovery, not for exact pricing
- Flight Offers Search is real-time but requires a specific destination — hence the two-step approach
- The test environment may not have full fare availability for all routes — some results may differ from production
- Amadeus currently does not return low-cost carrier fares (e.g., Ryanair, Flair) — this is a known limitation
- For Point Roberts, also consider SEA (Seattle) or BLI (Bellingham) as alternative origins
- Streamlit Community Cloud has a sleep policy for free apps — they spin down after inactivity and take ~30 seconds to wake up
