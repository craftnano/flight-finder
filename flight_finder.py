# Built by a GRC professional who is hoping if she gets replaced by AI,
# at least she can fly somewhere cheap
# Powered by Claude Code, Amadeus, and an unreasonable amount of Diet Coke
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from amadeus import Client, ResponseError
from amadeus.client.errors import (
    AuthenticationError,
    NetworkError,
    ServerError,
    ClientError,
    NotFoundError,
)
from dotenv import load_dotenv
from api_usage import increment_usage, get_usage

load_dotenv()

amadeus = Client(
    client_id=os.environ["AMADEUS_CLIENT_ID"],
    client_secret=os.environ["AMADEUS_CLIENT_SECRET"],
)

CABIN_CLASSES = ["ECONOMY", "BUSINESS", "FIRST"]

HUBS_BY_REGION = {
    "North America": [
        "SFO", "LAX", "SEA", "PDX", "YYC", "YYZ", "ORD", "JFK",
        "BOS", "IAD", "ATL", "DFW", "MIA", "DEN", "MSP",
    ],
    "Europe": [
        "LHR", "CDG", "AMS", "FRA", "MUC", "ZRH", "BCN", "MAD",
        "FCO", "CPH", "IST", "DUB",
    ],
    "Asia-Pacific": [
        "NRT", "HND", "ICN", "HKG", "SIN", "BKK", "TPE", "PVG",
        "SYD", "AKL",
    ],
    "Mexico/Caribbean": ["CUN", "MEX", "PVR", "SJD", "MBJ", "AUA"],
    "South America": ["GRU", "BOG", "SCL", "LIM", "EZE"],
    "Africa": ["JNB", "CPT", "NBO", "CAI", "ADD"],
    "Middle East": ["DXB", "DOH", "AUH", "TLV", "AMM"],
}

# If you're reading this, you're either debugging or procrastinating. Either way, welcome.
CITY_NAMES = {
    # North America — where "domestic" still means a 5-hour flight
    "YVR": "Vancouver", "YYC": "Calgary", "YYZ": "Toronto",
    "SFO": "San Francisco", "LAX": "Los Angeles", "SEA": "Seattle",
    "PDX": "Portland", "ORD": "Chicago", "JFK": "New York",
    "BOS": "Boston", "IAD": "Washington DC", "ATL": "Atlanta",
    "DFW": "Dallas", "MIA": "Miami", "DEN": "Denver", "MSP": "Minneapolis",
    "EWR": "Newark", "LGA": "New York", "DCA": "Washington DC",
    "OAK": "Oakland", "SJC": "San Jose", "BUR": "Burbank",
    "SNA": "Santa Ana", "ONT": "Ontario", "LGB": "Long Beach",
    "FLL": "Fort Lauderdale", "MDW": "Chicago", "DAL": "Dallas",
    "BLI": "Bellingham", "ANC": "Anchorage", "HNL": "Honolulu",
    # Europe — where the coffee is strong and the layovers are longer
    "LHR": "London", "CDG": "Paris", "AMS": "Amsterdam",
    "FRA": "Frankfurt", "MUC": "Munich", "ZRH": "Zurich",
    "BCN": "Barcelona", "MAD": "Madrid", "FCO": "Rome",
    "CPH": "Copenhagen", "IST": "Istanbul", "DUB": "Dublin",
    "ORY": "Paris", "LGW": "London", "STN": "London", "LTN": "London",
    # Asia-Pacific — where the future of aviation already landed
    "NRT": "Tokyo", "HND": "Tokyo", "ICN": "Seoul", "HKG": "Hong Kong",
    "SIN": "Singapore", "BKK": "Bangkok", "TPE": "Taipei",
    "PVG": "Shanghai", "SHA": "Shanghai", "PEK": "Beijing", "PKX": "Beijing",
    "SYD": "Sydney", "AKL": "Auckland", "MNL": "Manila", "KUL": "Kuala Lumpur",
    # Mexico/Caribbean — where the only turbulence is choosing a beach
    "CUN": "Cancun", "MEX": "Mexico City", "PVR": "Puerto Vallarta",
    "SJD": "San Jose del Cabo", "MBJ": "Montego Bay", "AUA": "Aruba",
    # South America — worth the long haul, every time
    "GRU": "Sao Paulo", "GIG": "Rio de Janeiro", "CGH": "Sao Paulo",
    "BOG": "Bogota", "SCL": "Santiago", "LIM": "Lima", "EZE": "Buenos Aires",
    # Africa — the final frontier for cheap business class
    "JNB": "Johannesburg", "CPT": "Cape Town", "NBO": "Nairobi",
    "CAI": "Cairo", "ADD": "Addis Ababa",
    # Middle East — where the lounges have lounges
    "DXB": "Dubai", "DOH": "Doha", "AUH": "Abu Dhabi",
    "TLV": "Tel Aviv", "AMM": "Amman",
}

SAME_CITY_SKIP = {
    "HND": "NRT",   # Tokyo
    "ORY": "CDG",   # Paris
    "LGW": "LHR",   # London
    "STN": "LHR",
    "LTN": "LHR",
    "EWR": "JFK",   # New York
    "LGA": "JFK",
    "MDW": "ORD",   # Chicago
    "SJC": "SFO",   # SF Bay Area
    "OAK": "SFO",
    "BUR": "LAX",   # Los Angeles
    "SNA": "LAX",
    "ONT": "LAX",
    "LGB": "LAX",
    "DCA": "IAD",   # Washington DC
    "FLL": "MIA",   # Miami / Fort Lauderdale
    "DAL": "DFW",   # Dallas
    "GIG": "GRU",   # Rio / Sao Paulo
    "CGH": "GRU",
    "PKX": "PEK",   # Beijing
    "SHA": "PVG",   # Shanghai
}


# ---------------------------------------------------------------------------
# Error handling
# If you're reading this, yes, I work in security. No, I couldn't leave API keys in the client.
# 20 years in GRC will do that to you.
# ---------------------------------------------------------------------------

class FlightSearchError(Exception):
    """User-friendly error with a message safe for st.error()."""
    def __init__(self, message, recoverable=True):
        self.message = message
        self.recoverable = recoverable
        super().__init__(message)


class ApiCapExceeded(FlightSearchError):
    def __init__(self):
        super().__init__(
            "Make Me Fly has been really popular today! "
            "To keep this free tool running, we limit daily searches. "
            "Please try again tomorrow.",
            recoverable=False,
        )


def _friendly_error(e, context="search"):
    """Convert a ResponseError into a FlightSearchError with a friendly message."""
    status = getattr(getattr(e, "response", None), "status_code", None)

    if isinstance(e, AuthenticationError) or status == 401:
        return FlightSearchError(
            "Make Me Fly is having trouble connecting to its data source. "
            "Please try again in a few minutes."
        )
    if status == 429:
        return FlightSearchError(
            "Searches are coming in faster than our data provider allows. "
            "Please wait a moment and try again."
        )
    if isinstance(e, ServerError) or (status and status >= 500):
        return FlightSearchError(
            "Our flight data provider is experiencing issues. "
            "This isn't you — please try again shortly."
        )
    if isinstance(e, NetworkError):
        return FlightSearchError(
            "The search is taking longer than expected. Please try again."
        )

    # Check for quota/limit errors in the response body
    body = getattr(getattr(e, "response", None), "body", "") or ""
    if "quota" in body.lower() or "limit" in body.lower():
        return FlightSearchError(
            "Make Me Fly has been popular this month! "
            "We've hit our data limit. Resets on the 1st."
        )

    return FlightSearchError("Something unexpected happened. Please try again.")


def _check_cap():
    """Check API cap and raise if exceeded."""
    if not increment_usage(1):
        raise ApiCapExceeded()


# ---------------------------------------------------------------------------
# Core API functions — where dreams become HTTP requests
# ---------------------------------------------------------------------------

def get_direct_destinations(origin="YVR"):
    """Get all airports with direct flights from origin."""
    _check_cap()
    try:
        response = amadeus.airport.direct_destinations.get(
            departureAirportCode=origin
        )
        return [d["iataCode"] for d in response.data]
    except ResponseError as e:
        raise _friendly_error(e, "destination lookup")


def discover_destinations(origin="YVR", departure_date=None, max_price=None):
    """
    Find destinations from origin. Tries Inspiration Search first,
    falls back to Direct Destinations.
    """
    params = {"origin": origin}
    if departure_date:
        params["departureDate"] = departure_date
    if max_price:
        params["maxPrice"] = max_price

    _check_cap()
    try:
        response = amadeus.shopping.flight_destinations.get(**params)
        return response.data
    except ResponseError:
        pass

    codes = get_direct_destinations(origin)
    return [{"destination": code} for code in codes]


def search_flights(
    origin="YVR",
    destination="NRT",
    departure_date="2026-03-15",
    return_date=None,
    cabin="BUSINESS",
    adults=1,
    max_results=10,
    currency="CAD",
    nonstop=False,
    max_price=None,
):
    """Search for flights on a specific route with cabin class."""
    _check_cap()
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": adults,
        "travelClass": cabin,
        "max": max_results,
        "currencyCode": currency,
    }
    if nonstop:
        params["nonStop"] = "true"
    if return_date:
        params["returnDate"] = return_date
    if max_price:
        params["maxPrice"] = max_price

    try:
        response = amadeus.shopping.flight_offers_search.get(**params)
        return response.data
    except ResponseError as e:
        raise _friendly_error(e, "flight search")


def search_anywhere(
    origin="YVR",
    departure_date=None,
    return_date=None,
    cabins=None,
    top_n=10,
    adults=1,
    currency="CAD",
    nonstop=False,
    on_progress=None,
):
    """Legacy sequential search. Kept for test scripts."""
    if cabins is None:
        cabins = ["ECONOMY", "BUSINESS"]

    destinations = discover_destinations(origin, departure_date)
    if not destinations:
        return {}

    if not departure_date:
        from datetime import date, timedelta
        departure_date = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")

    top_dests = destinations[:top_n]
    all_results = {}
    for cabin in cabins:
        cabin_results = []
        for dest_info in top_dests:
            dest_code = dest_info["destination"]
            dep_date = departure_date or dest_info.get("departureDate")
            ret_date = return_date or dest_info.get("returnDate")

            if on_progress:
                on_progress(cabin, dest_code)

            try:
                flights = search_flights(
                    origin=origin,
                    destination=dest_code,
                    departure_date=dep_date,
                    return_date=ret_date,
                    cabin=cabin,
                    adults=adults,
                    currency=currency,
                    nonstop=nonstop,
                )
                if flights:
                    cabin_results.extend(flights)
            except FlightSearchError:
                continue

        cabin_results.sort(key=lambda f: float(f["price"]["grandTotal"]))
        all_results[cabin] = cabin_results

    return all_results


def get_price_analysis(origin, destination, departure_date):
    """Get price metrics for a route using Amadeus Price Analysis API."""
    _check_cap()
    try:
        response = amadeus.analytics.itinerary_price_metrics.get(
            originIataCode=origin,
            destinationIataCode=destination,
            departureDate=departure_date,
        )
        return response.data
    except ResponseError:
        return None


# The real question isn't "can I afford business class?"
# It's "is the multiplier low enough to justify it to myself?"
def compute_upgrade_value(all_results):
    """Compare economy vs business prices for overlapping destinations."""
    def cheapest_by_dest(flights):
        by_dest = {}
        for f in flights:
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


# ---------------------------------------------------------------------------
# Destination helpers
# ---------------------------------------------------------------------------

def dedup_destinations(codes):
    """Remove secondary airports that serve the same city as a primary."""
    seen_primary = set()
    result = []
    for code in codes:
        primary = SAME_CITY_SKIP.get(code, code)
        if primary not in seen_primary:
            seen_primary.add(primary)
            result.append(primary)
    return result


def get_hub_destinations(regions=None):
    """Get curated hub destinations, optionally filtered by region."""
    if regions:
        codes = []
        for region in regions:
            codes.extend(HUBS_BY_REGION.get(region, []))
        return codes
    return [code for codes in HUBS_BY_REGION.values() for code in codes]


# ---------------------------------------------------------------------------
# Parallel search
# Running these in parallel because life is too short to search destinations one at a time
# Just like business class upgrades — the value is in doing things simultaneously
# ---------------------------------------------------------------------------

def search_parallel(
    origin,
    destinations,
    departure_date,
    return_date,
    cabins,
    currency="CAD",
    nonstop=False,
    max_price=None,
    adults=1,
    max_results=5,
    max_workers=8,
    on_progress=None,
):
    """Search multiple destinations and cabins in parallel."""
    jobs = [(cabin, dest) for cabin in cabins for dest in destinations]
    results_by_cabin = {cabin: [] for cabin in cabins}

    def do_search(cabin, dest):
        return cabin, dest, search_flights(
            origin=origin,
            destination=dest,
            departure_date=departure_date,
            return_date=return_date,
            cabin=cabin,
            adults=adults,
            max_results=max_results,
            currency=currency,
            nonstop=nonstop,
            max_price=max_price,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(do_search, cabin, dest): (cabin, dest)
            for cabin, dest in jobs
        }
        for future in as_completed(futures):
            cabin, dest = futures[future]
            if on_progress:
                on_progress(cabin, dest)
            try:
                cabin, dest, flights = future.result()
                if flights:
                    results_by_cabin[cabin].extend(flights)
            except ApiCapExceeded:
                raise
            except FlightSearchError:
                continue

    for cabin in cabins:
        results_by_cabin[cabin].sort(
            key=lambda f: float(f["price"]["grandTotal"])
        )

    return results_by_cabin


# ---------------------------------------------------------------------------
# Flexible date search
# Because the cheapest flight is always on the day you didn't check
# ---------------------------------------------------------------------------

def search_flexible(
    origin, destinations, sample_dep_dates, trip_length_days, cabins,
    currency="CAD", nonstop=False, max_price=None, max_workers=8,
):
    """
    Search multiple sample departure dates per destination and return
    the cheapest date found for each (cabin, dest) pair.
    """
    from datetime import datetime, timedelta

    # Build (dep_date, ret_date) pairs
    date_pairs = []
    for dep_str in sample_dep_dates:
        dep_dt = datetime.strptime(dep_str, "%Y-%m-%d")
        ret_dt = dep_dt + timedelta(days=trip_length_days)
        date_pairs.append((dep_str, ret_dt.strftime("%Y-%m-%d")))

    # Jobs: (cabin, dest, dep_date, ret_date)
    jobs = [
        (cabin, dest, dep, ret)
        for cabin in cabins
        for dest in destinations
        for dep, ret in date_pairs
    ]

    # Track cheapest per (cabin, dest, date) and overall cheapest per (cabin, dest)
    # best[(cabin, dest)] = {"price": float, "date": str, "flight": obj,
    #                         "max_price": float, "dates_checked": int, "prices": []}
    best = {}

    def do_search(cabin, dest, dep, ret):
        return cabin, dest, dep, search_flights(
            origin=origin,
            destination=dest,
            departure_date=dep,
            return_date=ret,
            cabin=cabin,
            adults=1,
            max_results=3,
            currency=currency,
            nonstop=nonstop,
            max_price=max_price,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(do_search, cab, dst, dep, ret): (cab, dst, dep)
            for cab, dst, dep, ret in jobs
        }
        for future in as_completed(futures):
            cab, dst, dep = futures[future]
            try:
                cabin, dest, dep_date, flights = future.result()
                if not flights:
                    continue
                # Cheapest flight in this result set
                cheapest_flight = min(
                    flights, key=lambda f: float(f["price"]["grandTotal"])
                )
                price = float(cheapest_flight["price"]["grandTotal"])
                key = (cabin, dest)
                if key not in best:
                    best[key] = {
                        "price": price,
                        "date": dep_date,
                        "flight": cheapest_flight,
                        "prices": [price],
                    }
                else:
                    best[key]["prices"].append(price)
                    if price < best[key]["price"]:
                        best[key]["price"] = price
                        best[key]["date"] = dep_date
                        best[key]["flight"] = cheapest_flight
            except ApiCapExceeded:
                raise
            except FlightSearchError:
                continue

    # Build final structure: {cabin: {dest: {...}}}
    result = {cabin: {} for cabin in cabins}
    for (cabin, dest), info in best.items():
        max_price_found = max(info["prices"])
        result[cabin][dest] = {
            "flight": info["flight"],
            "price": info["price"],
            "date": info["date"],
            "max_price_found": max_price_found,
            "savings": max_price_found - info["price"],
            "dates_checked": len(info["prices"]),
        }

    return result


# ---------------------------------------------------------------------------
# Airline name lookup
# ---------------------------------------------------------------------------

_airline_cache = {}

# Corporate suffixes: because "ACME AIRLINES LTD. D/B/A FLYING CORP." is not a name, it's a legal filing
_STRIP_SUFFIXES = [
    " D/B/A", " LTD.", " LTD", " INC.", " INC", " CORP.", " CORP",
    " CO.", " CO", " S.A.", " S.A", " SA", " AG", " GMBH",
    " LLC", " PLC", " GROUP", " HOLDINGS", " ENTERPRISES",
    " PTY", " NV", " BV", " SE",
]


def clean_airline_name(raw_name):
    """Strip corporate suffixes and title-case an airline name."""
    if not raw_name or len(raw_name) <= 2:
        return raw_name
    name = raw_name.upper()
    changed = True
    while changed:
        changed = False
        for suffix in _STRIP_SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)].rstrip()
                changed = True
    # Title case, but preserve known all-caps like "KLM" or "SAS"
    if len(name) <= 3:
        return name
    return name.title()


def lookup_airlines_batch(codes):
    """Look up airline names by IATA codes. Single API call for all unknowns."""
    to_fetch = [c for c in codes if c not in _airline_cache]
    if to_fetch:
        try:
            _check_cap()
            codes_str = ",".join(to_fetch)
            response = amadeus.reference_data.airlines.get(airlineCodes=codes_str)
            for airline in (response.data or []):
                iata = airline.get("iataCode", "")
                name = (airline.get("businessName")
                        or airline.get("commonName")
                        or iata)
                _airline_cache[iata] = clean_airline_name(name)
        except (ResponseError, FlightSearchError):
            pass
        # Cache misses as code→code so we don't retry
        for code in to_fetch:
            if code not in _airline_cache:
                _airline_cache[code] = code

    return {code: _airline_cache.get(code, code) for code in codes}


# ---------------------------------------------------------------------------
# Deal score
# ---------------------------------------------------------------------------

def compute_deal_label(price, price_data):
    """Compare price against quartile thresholds from price analysis."""
    if not price_data:
        return "N/A"

    # price_data is a list; first item has priceMetrics
    metrics_list = None
    if isinstance(price_data, list) and len(price_data) > 0:
        metrics_list = price_data[0].get("priceMetrics", [])
    elif isinstance(price_data, dict):
        metrics_list = price_data.get("priceMetrics", [])

    if not metrics_list:
        return "N/A"

    thresholds = {}
    for m in metrics_list:
        ranking = m.get("quartileRanking", "")
        try:
            thresholds[ranking] = float(m.get("amount", 0))
        except (ValueError, TypeError):
            continue

    first = thresholds.get("FIRST")
    medium = thresholds.get("MEDIUM")
    third = thresholds.get("THIRD")

    if first is not None and price <= first:
        return "Great Deal"
    if medium is not None and price <= medium:
        return "Good Price"
    if third is not None and price <= third:
        return "Average"
    if third is not None:
        return "Above Average"
    return "N/A"


def get_deal_scores_parallel(origin, destinations, departure_date):
    """Fetch price analysis for multiple destinations in parallel."""
    scores = {}

    def fetch(dest):
        return dest, get_price_analysis(origin, dest, departure_date)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch, d): d for d in destinations}
        for future in as_completed(futures):
            dest = futures[future]
            try:
                dest, data = future.result()
                scores[dest] = data
            except Exception:
                scores[dest] = None

    return scores


# ---------------------------------------------------------------------------
# Flight delay prediction
# ---------------------------------------------------------------------------

def predict_delay(segment):
    """
    Predict on-time probability for a flight segment.
    Returns a string like "92% on-time" or None on failure.
    """
    try:
        dep_dt = segment["departure"]["at"]
        arr_dt = segment["arrival"]["at"]

        _check_cap()
        response = amadeus.travel.predictions.flight_delay.get(
            originLocationCode=segment["departure"]["iataCode"],
            destinationLocationCode=segment["arrival"]["iataCode"],
            departureDate=dep_dt[:10],
            departureTime=dep_dt[11:19] or "00:00:00",
            arrivalDate=arr_dt[:10],
            arrivalTime=arr_dt[11:19] or "00:00:00",
            aircraftCode=segment.get("aircraft", {}).get("code", "000"),
            carrierCode=segment["carrierCode"],
            flightNumber=segment["number"],
            duration=segment.get("duration", "PT0H"),
        )

        if not response.data:
            return None

        # Response is a list of prediction objects with id and probability
        # Find the one for "LESS_THAN_30_MINUTES" (on-time + minor delay)
        for item in response.data:
            result = item.get("result", item)
            if isinstance(result, dict):
                on_time = result.get("LESS_THAN_30_MINUTES")
                if on_time is not None:
                    return f"{float(on_time) * 100:.0f}% on-time"

            # Alternative format: item has subType and probability
            prob = item.get("probability")
            if prob is not None:
                return f"{float(prob) * 100:.0f}% on-time"

        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Google Flights URL
# ---------------------------------------------------------------------------

def google_flights_url(origin, dest, dep_date, cabin="ECONOMY"):
    """Build a Google Flights search URL."""
    cabin_map = {"ECONOMY": "economy", "BUSINESS": "business", "FIRST": "first"}
    cabin_str = cabin_map.get(cabin, "economy")
    return (
        f"https://www.google.com/travel/flights"
        f"?q=Flights+to+{dest}+from+{origin}+on+{dep_date}"
        f"+{cabin_str}+class"
    )
