# "Make me fly" — for people who want to go somewhere but don't know where
# Basically Zillow's "Make Me Move" but with more turbulence
import os
import time
import streamlit as st
from datetime import date, timedelta
from flight_finder import (
    search_parallel,
    search_flexible,
    compute_upgrade_value,
    get_direct_destinations,
    get_hub_destinations,
    dedup_destinations,
    lookup_airlines_batch,
    get_deal_scores_parallel,
    compute_deal_label,
    predict_delay,
    google_flights_url,
    FlightSearchError,
    ApiCapExceeded,
    HUBS_BY_REGION,
    CITY_NAMES,
)
from api_usage import get_usage
from ip_limiter import check_ip_limit, get_ip_usage
import pandas as pd

st.set_page_config(page_title="Make Me Fly", page_icon="✈️", layout="wide")

# --- Logo ---
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "makemefly-logo.svg")
if os.path.exists(LOGO_PATH):
    col_l, col_logo, col_r = st.columns([1, 2, 1])
    with col_logo:
        st.image(LOGO_PATH, use_container_width=True)
else:
    st.title("✈️ Make Me Fly")
    st.caption("Discover your next adventure.")

# Rate limiting: because going viral should be a celebration, not a billing event
if "search_count" not in st.session_state:
    st.session_state.search_count = 0
    st.session_state.search_reset = date.today()

if st.session_state.search_reset < date.today():
    st.session_state.search_count = 0
    st.session_state.search_reset = date.today()

MAX_SEARCHES_PER_DAY = 20

# Amadeus test env returns prices in the origin airport's local currency,
# not the requested currency. Map airports to their actual currency.
AIRPORT_CURRENCY = {
    # Canada — CAD
    "YVR": "CAD", "YYC": "CAD", "YYZ": "CAD",
    # United States — USD
    "SFO": "USD", "LAX": "USD", "SEA": "USD", "PDX": "USD", "ORD": "USD",
    "JFK": "USD", "BOS": "USD", "IAD": "USD", "ATL": "USD", "DFW": "USD",
    "MIA": "USD", "DEN": "USD", "MSP": "USD", "EWR": "USD", "LGA": "USD",
    "DCA": "USD", "OAK": "USD", "SJC": "USD", "BUR": "USD", "SNA": "USD",
    "ONT": "USD", "LGB": "USD", "FLL": "USD", "MDW": "USD", "DAL": "USD",
    "BLI": "USD", "ANC": "USD", "HNL": "USD",
    # Europe — EUR (eurozone)
    "CDG": "EUR", "ORY": "EUR", "AMS": "EUR", "FRA": "EUR", "MUC": "EUR",
    "BCN": "EUR", "MAD": "EUR", "FCO": "EUR", "DUB": "EUR",
    # Europe — non-EUR
    "LHR": "GBP", "LGW": "GBP", "STN": "GBP", "LTN": "GBP",
    "ZRH": "CHF",
    "CPH": "DKK",
    "IST": "TRY",
    # Asia-Pacific
    "NRT": "JPY", "HND": "JPY",
    "ICN": "KRW",
    "HKG": "HKD",
    "SIN": "SGD",
    "BKK": "THB",
    "TPE": "TWD",
    "PVG": "CNY", "SHA": "CNY", "PEK": "CNY", "PKX": "CNY",
    "SYD": "AUD",
    "AKL": "NZD",
    "MNL": "PHP",
    "KUL": "MYR",
    # Mexico/Caribbean
    "CUN": "MXN", "MEX": "MXN", "PVR": "MXN", "SJD": "MXN",
    "MBJ": "USD", "AUA": "USD",
    # South America
    "GRU": "BRL", "GIG": "BRL", "CGH": "BRL",
    "BOG": "COP", "SCL": "CLP", "LIM": "PEN", "EZE": "ARS",
    # Africa
    "JNB": "ZAR", "CPT": "ZAR",
    "NBO": "KES",
    "CAI": "EGP",
    "ADD": "ETB",
    # Middle East
    "DXB": "AED", "AUH": "AED",
    "DOH": "QAR",
    "TLV": "ILS",
    "AMM": "JOD",
}


def detect_currency(iata_code):
    """Return the local currency for an airport code, defaulting to USD."""
    return AIRPORT_CURRENCY.get(iata_code, "USD")


# Cache results for 30 min because flight prices don't change that fast
# and my Amadeus free tier definitely does run out that fast
@st.cache_data(ttl=1800, show_spinner=False)
def run_search(origin, dep_str, ret_str, cabins_tuple, dest_tuple, currency,
               nonstop, max_price):
    """Cached parallel search. Results stored for 30 minutes."""
    return search_parallel(
        origin=origin,
        destinations=list(dest_tuple),
        departure_date=dep_str,
        return_date=ret_str,
        cabins=list(cabins_tuple),
        currency=currency,
        nonstop=nonstop,
        max_price=max_price,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def run_flexible_search(origin, sample_dates_tuple, trip_length, cabins_tuple,
                        dest_tuple, currency, nonstop, max_price):
    """Cached flexible date search. Results stored for 30 minutes."""
    return search_flexible(
        origin=origin,
        destinations=list(dest_tuple),
        sample_dep_dates=list(sample_dates_tuple),
        trip_length_days=trip_length,
        cabins=list(cabins_tuple),
        currency=currency,
        nonstop=nonstop,
        max_price=max_price,
    )


# --- Sidebar: Search Parameters ---
with st.sidebar:
    st.header("Search Settings")

    fly_from = st.text_input("From (IATA code)", value="YVR",
                             help="e.g., YVR, SEA, BLI, SFO, LHR").upper().strip()

    cabins = st.multiselect("Cabin class",
                            ["ECONOMY", "BUSINESS", "FIRST"],
                            default=["ECONOMY", "BUSINESS"])

    date_mode = st.radio(
        "Date mode",
        ["Fixed dates", "Flexible dates (find cheapest days)"],
    )

    if date_mode == "Fixed dates":
        col1, col2 = st.columns(2)
        with col1:
            dep_date = st.date_input("Departure date",
                                     value=date.today() + timedelta(days=30))
        with col2:
            ret_date = st.date_input("Return date",
                                     value=dep_date + timedelta(days=7))
        flex_month = None
        trip_length = None
        sample_dates = []
    else:
        dep_date = None
        ret_date = None
        # Generate next 6 months
        month_options = []
        today = date.today()
        cur_year, cur_month = today.year, today.month
        for i in range(6):
            m = cur_month + i
            y = cur_year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            month_options.append(date(y, m, 1))
        flex_month = st.selectbox(
            "Month",
            month_options,
            format_func=lambda d: d.strftime("%B %Y"),
        )
        trip_length = st.selectbox(
            "Trip length (days)", [3, 5, 7, 10, 14], index=2,
        )
        # Sample dates: 1st, 8th, 15th, 22nd — skip past dates
        sample_dates = []
        for day in [1, 8, 15, 22]:
            try:
                d = date(flex_month.year, flex_month.month, day)
            except ValueError:
                continue
            if d > today:
                sample_dates.append(d.strftime("%Y-%m-%d"))
        st.warning(
            "Flexible search checks 4 dates per destination "
            "— uses ~4× more API calls than fixed date search."
        )

    search_mode = st.radio(
        "Search mode",
        ["Major hubs only (faster)", "All destinations (thorough)"],
        help="Major hubs searches a curated list of tier 1 airports. "
             "All destinations uses the Amadeus direct routes API.",
    )

    if search_mode == "Major hubs only (faster)":
        regions = st.multiselect(
            "Regions",
            list(HUBS_BY_REGION.keys()),
            default=list(HUBS_BY_REGION.keys()),
        )
    else:
        regions = None

    max_price = st.slider(
        "Maximum price",
        min_value=500, max_value=10000, value=5000, step=250,
        format="$%d",
        help="Server-side filter — only returns flights under this price.",
    )

    nonstop = st.checkbox("Nonstop flights only")
    show_delays = st.checkbox("Show on-time prediction",
                              help="Uses additional API calls per flight")

    currency = detect_currency(fly_from)
    st.caption(f"Currency: {currency} (based on departure airport)")

    remaining = MAX_SEARCHES_PER_DAY - st.session_state.search_count
    st.caption(f"Searches remaining today: {remaining}")

    # API usage display
    calls_today, daily_cap = get_usage()
    st.caption(f"API calls today: {calls_today}/{daily_cap}")

    search = st.button("🔍 Search Flights", type="primary",
                       use_container_width=True,
                       disabled=(remaining <= 0 or not cabins or len(fly_from) != 3))

# --- Validation ---
if date_mode == "Fixed dates":
    date_error = dep_date >= ret_date
    if date_error:
        st.warning("Return date must be after departure date.")
else:
    date_error = len(sample_dates) == 0
    if date_error:
        st.warning("All sample dates for this month have already passed. "
                   "Choose a later month.")

# --- Main: Results ---
if search and not date_error:
    # Get client IP for rate limiting
    _headers = st.context.headers
    client_ip = (
        _headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or _headers.get("X-Real-Ip", "")
        or "unknown"
    )

    # Check IP rate limit
    if not check_ip_limit(client_ip):
        st.error(
            "You've reached the daily search limit. "
            "Make Me Fly limits searches per user to keep the service "
            "free for everyone. Please try again tomorrow."
        )
        st.stop()

    st.session_state.search_count += 1

    # Check API cap before starting
    calls_now, cap = get_usage()
    if calls_now >= cap:
        st.error(
            "Make Me Fly has been really popular today! "
            "To keep this free tool running, we limit daily searches. "
            "Please try again tomorrow."
        )
    else:
        # Build destination list
        try:
            if search_mode == "Major hubs only (faster)":
                dest_list = get_hub_destinations(regions)
            else:
                with st.spinner("Loading destinations..."):
                    dest_list = get_direct_destinations(fly_from)
        except FlightSearchError as e:
            st.error(e.message)
            dest_list = []

        dest_list = dedup_destinations(dest_list)
        dest_list = [d for d in dest_list if d != fly_from]

        if not dest_list:
            if not isinstance(dest_list, list) or len(dest_list) == 0:
                st.warning("No destinations found. Try a different origin "
                           "or search mode.")

        elif date_mode == "Flexible dates (find cheapest days)":
            # ----- FLEXIBLE DATE SEARCH -----
            n_dests = len(dest_list)
            n_dates = len(sample_dates)
            n_calls = n_dests * len(cabins) * n_dates

            timer_slot = st.empty()
            start_time = time.time()

            try:
                with st.spinner(
                    f"Flexible search: {n_dests} destinations × "
                    f"{len(cabins)} cabin{'s' if len(cabins) > 1 else ''} × "
                    f"{n_dates} dates ({n_calls} queries, 8 parallel)..."
                ):
                    flex_results = run_flexible_search(
                        fly_from,
                        tuple(sample_dates),
                        trip_length,
                        tuple(cabins),
                        tuple(dest_list),
                        currency,
                        nonstop,
                        max_price,
                    )
            except ApiCapExceeded:
                st.error(
                    "Make Me Fly has been really popular today! "
                    "To keep this free tool running, we limit daily searches. "
                    "Please try again tomorrow."
                )
                st.stop()
            except FlightSearchError as e:
                st.error(e.message)
                st.stop()

            elapsed = time.time() - start_time

            has_results = any(
                len(dests) > 0 for dests in flex_results.values()
            )
            if not has_results:
                timer_slot.empty()
                st.info(
                    "No flights found. Try a different month, "
                    "a larger search, or disable nonstop."
                )
            else:
                if elapsed < 1.0:
                    timer_slot.caption("⚡ Results loaded from cache")
                else:
                    timer_slot.caption(
                        f"⏱ Results found in {elapsed:.1f} seconds "
                        f"({n_dests} destinations × {n_dates} dates)"
                    )

                st.caption(
                    "Prices shown in the local currency of your "
                    "departure airport."
                )

                # Collect carrier codes for airline lookup
                all_carrier_codes = set()
                for cab_dests in flex_results.values():
                    for info in cab_dests.values():
                        flight = info["flight"]
                        for seg in flight["itineraries"][0]["segments"]:
                            all_carrier_codes.add(seg["carrierCode"])

                try:
                    airline_names = lookup_airlines_batch(all_carrier_codes)
                except FlightSearchError:
                    airline_names = {c: c for c in all_carrier_codes}

                # Display per cabin
                for cabin_name in cabins:
                    cab_dests = flex_results.get(cabin_name, {})
                    st.subheader(f"{cabin_name.title()} Class — Best Dates")

                    if not cab_dests:
                        st.info(f"No {cabin_name.lower()} flights found.")
                        continue

                    sorted_dests = sorted(
                        cab_dests.items(),
                        key=lambda x: x[1]["price"],
                    )

                    rows = []
                    for dest, info in sorted_dests:
                        flight = info["flight"]
                        segments = flight["itineraries"][0]["segments"]
                        airlines = ", ".join(sorted(set(
                            airline_names.get(
                                s["carrierCode"], s["carrierCode"]
                            )
                            for s in segments
                        )))
                        stops = len(segments) - 1
                        duration = flight["itineraries"][0].get(
                            "duration", ""
                        )
                        best_date = info["date"]
                        ret_dt = (
                            date.fromisoformat(best_date)
                            + timedelta(days=trip_length)
                        )
                        book_url = google_flights_url(
                            fly_from, dest, best_date, cabin_name
                        )

                        city = CITY_NAMES.get(dest)
                        dest_label = (
                            "%s (%s)" % (city, dest) if city else dest
                        )

                        if (info["dates_checked"] > 1
                                and info["savings"] > 0):
                            savings_str = f"Save ${info['savings']:,.0f}"
                        else:
                            savings_str = "\u2014"

                        row = {
                            "Destination": dest_label,
                            "Best Date": best_date,
                            "Return": ret_dt.strftime("%Y-%m-%d"),
                            "Price": f"${info['price']:,.0f} {currency}",
                            "Savings": savings_str,
                            "Airlines": airlines,
                            "Stops": stops,
                            "Duration": duration.replace(
                                "PT", ""
                            ).lower(),
                            "Book": book_url,
                        }
                        rows.append(row)

                    df = pd.DataFrame(rows)

                    col_config = {
                        "Book": st.column_config.LinkColumn(
                            "Book", display_text="Book ➜"
                        ),
                    }
                    st.dataframe(
                        df, column_config=col_config,
                        use_container_width=True, hide_index=True,
                    )

                    csv_data = df.to_csv(index=False)
                    st.download_button(
                        label=(
                            f"📥 Download {cabin_name.title()} "
                            f"flexible results as CSV"
                        ),
                        data=csv_data,
                        file_name=(
                            f"makemefly_flex_{cabin_name.lower()}"
                            f"_{fly_from}_{flex_month.strftime('%Y%m')}.csv"
                        ),
                        mime="text/csv",
                    )

                # Upgrade value analysis for flexible results
                if ("ECONOMY" in flex_results
                        and "BUSINESS" in flex_results
                        and flex_results["ECONOMY"]
                        and flex_results["BUSINESS"]):
                    upgrade_input = {
                        cab: [
                            info["flight"]
                            for info in dests.values()
                        ]
                        for cab, dests in flex_results.items()
                        if cab in ("ECONOMY", "BUSINESS")
                    }
                    comparisons = compute_upgrade_value(upgrade_input)
                    if comparisons:
                        st.subheader("💎 Upgrade Value Analysis")
                        st.caption(
                            "Lower multiplier = "
                            "better deal on business class"
                        )
                        comp_df = pd.DataFrame([{
                            "Destination": (
                                "%s (%s)" % (
                                    CITY_NAMES[c["destination"]],
                                    c["destination"],
                                )
                                if c["destination"] in CITY_NAMES
                                else c["destination"]
                            ),
                            f"Economy ({currency})":
                                f"${c['economy']:,.0f}",
                            f"Business ({currency})":
                                f"${c['business']:,.0f}",
                            "Premium": f"${c['premium']:,.0f}",
                            "Multiplier":
                                f"{c['multiplier']:.1f}x",
                        } for c in comparisons])
                        st.dataframe(
                            comp_df, use_container_width=True,
                            hide_index=True,
                        )

                        csv_data = comp_df.to_csv(index=False)
                        st.download_button(
                            label=(
                                "📥 Download upgrade analysis as CSV"
                            ),
                            data=csv_data,
                            file_name=(
                                f"makemefly_upgrade_{fly_from}"
                                f"_{flex_month.strftime('%Y%m')}.csv"
                            ),
                            mime="text/csv",
                        )

        else:
            # ----- FIXED DATE SEARCH (existing behavior) -----
            dep_str = dep_date.strftime("%Y-%m-%d")
            ret_str = ret_date.strftime("%Y-%m-%d")
            n_dests = len(dest_list)
            n_calls = n_dests * len(cabins)

            # Search with timer
            timer_slot = st.empty()
            start_time = time.time()

            try:
                with st.spinner(
                    f"Searching {n_dests} destinations × "
                    f"{len(cabins)} cabin{'s' if len(cabins) > 1 else ''} "
                    f"({n_calls} queries, 8 parallel)..."
                ):
                    results = run_search(
                        fly_from, dep_str, ret_str,
                        tuple(cabins), tuple(dest_list), currency, nonstop,
                        max_price,
                    )
            except ApiCapExceeded:
                st.error(
                    "Make Me Fly has been really popular today! "
                    "To keep this free tool running, we limit daily searches. "
                    "Please try again tomorrow."
                )
                st.stop()
            except FlightSearchError as e:
                st.error(e.message)
                st.stop()

            elapsed = time.time() - start_time

            if not results or all(len(v) == 0 for v in results.values()):
                timer_slot.empty()
                st.info(
                    "No flights found. Try different dates, "
                    "a larger search, or disable nonstop."
                )
            else:
                if elapsed < 1.0:
                    timer_slot.caption("⚡ Results loaded from cache")
                else:
                    timer_slot.caption(
                        f"⏱ Results found in {elapsed:.1f} seconds "
                        f"({n_dests} destinations)"
                    )

                st.caption(
                    "Prices shown in the local currency of your "
                    "departure airport."
                )

                # --- Enrich results ---

                # 1. Collect all carrier codes for airline name lookup
                all_carrier_codes = set()
                for flights in results.values():
                    for f in flights:
                        for seg in f["itineraries"][0]["segments"]:
                            all_carrier_codes.add(seg["carrierCode"])

                try:
                    airline_names = lookup_airlines_batch(all_carrier_codes)
                except FlightSearchError:
                    airline_names = {c: c for c in all_carrier_codes}

                # 2. Dedup: cheapest per destination per cabin
                deduped_results = {}
                for cabin_name, flights in results.items():
                    cheapest = {}
                    for f in flights:
                        segs = f["itineraries"][0]["segments"]
                        dest = segs[-1]["arrival"]["iataCode"]
                        price = float(f["price"]["grandTotal"])
                        if dest not in cheapest or price < cheapest[dest][1]:
                            cheapest[dest] = (f, price)
                    deduped_results[cabin_name] = cheapest

                # 3. Collect unique destinations for deal scores
                unique_dests = set()
                for cheapest in deduped_results.values():
                    unique_dests.update(cheapest.keys())

                try:
                    deal_data = get_deal_scores_parallel(
                        fly_from, list(unique_dests), dep_str
                    )
                except FlightSearchError:
                    deal_data = {}

                # 4. Delay predictions (if enabled)
                delay_results = {}
                if show_delays:
                    delay_status = st.empty()
                    delay_status.text("Fetching on-time predictions...")
                    for cabin_name, cheapest in deduped_results.items():
                        for dest, (flight, _price) in cheapest.items():
                            key = (cabin_name, dest)
                            seg = flight["itineraries"][0]["segments"][0]
                            delay_results[key] = predict_delay(seg) or "N/A"
                    delay_status.empty()

                # --- Display results per cabin ---
                for cabin_name, cheapest in deduped_results.items():
                    st.subheader(f"{cabin_name.title()} Class")

                    if not cheapest:
                        st.info(f"No {cabin_name.lower()} flights found.")
                        continue

                    sorted_dests = sorted(
                        cheapest.items(), key=lambda x: x[1][1]
                    )

                    rows = []
                    for dest, (f, price_val) in sorted_dests:
                        segments = f["itineraries"][0]["segments"]
                        airlines = ", ".join(sorted(set(
                            airline_names.get(s["carrierCode"], s["carrierCode"])
                            for s in segments
                        )))
                        stops = len(segments) - 1
                        duration = f["itineraries"][0].get("duration", "")
                        deal_label = compute_deal_label(
                            price_val, deal_data.get(dest)
                        )
                        book_url = google_flights_url(
                            fly_from, dest, dep_str, cabin_name
                        )

                        city = CITY_NAMES.get(dest)
                        dest_label = "%s (%s)" % (city, dest) if city else dest

                        row = {
                            "Destination": dest_label,
                            "Price": f"${price_val:,.0f} {currency}",
                            "Deal": deal_label,
                            "Departure": segments[0]["departure"]["at"][:10],
                            "Airlines": airlines,
                            "Stops": stops,
                            "Duration": duration.replace("PT", "").lower(),
                        }

                        if show_delays:
                            key = (cabin_name, dest)
                            row["On-Time"] = delay_results.get(key, "N/A")

                        row["Book"] = book_url
                        rows.append(row)

                    df = pd.DataFrame(rows)

                    col_config = {
                        "Book": st.column_config.LinkColumn(
                            "Book", display_text="Book ➜"
                        ),
                    }
                    st.dataframe(
                        df, column_config=col_config,
                        use_container_width=True, hide_index=True,
                    )

                    # CSV download
                    csv_data = df.to_csv(index=False)
                    st.download_button(
                        label=f"📥 Download {cabin_name.title()} results as CSV",
                        data=csv_data,
                        file_name=(f"makemefly_{cabin_name.lower()}"
                                   f"_{fly_from}_{dep_str}.csv"),
                        mime="text/csv",
                    )

                # --- Upgrade value analysis ---
                if "ECONOMY" in deduped_results and "BUSINESS" in deduped_results:
                    # Rebuild in the format compute_upgrade_value expects
                    upgrade_input = {}
                    for cabin_name, cheapest in deduped_results.items():
                        if cabin_name in ("ECONOMY", "BUSINESS"):
                            upgrade_input[cabin_name] = [
                                f for f, _p in cheapest.values()
                            ]

                    comparisons = compute_upgrade_value(upgrade_input)
                    if comparisons:
                        st.subheader("💎 Upgrade Value Analysis")
                        st.caption(
                            "Lower multiplier = "
                            "better deal on business class"
                        )
                        comp_df = pd.DataFrame([{
                            "Destination": (
                                "%s (%s)" % (CITY_NAMES[c["destination"]], c["destination"])
                                if c["destination"] in CITY_NAMES
                                else c["destination"]
                            ),
                            f"Economy ({currency})":
                                f"${c['economy']:,.0f}",
                            f"Business ({currency})":
                                f"${c['business']:,.0f}",
                            "Premium": f"${c['premium']:,.0f}",
                            "Multiplier": f"{c['multiplier']:.1f}x",
                        } for c in comparisons])
                        st.dataframe(
                            comp_df, use_container_width=True,
                            hide_index=True,
                        )

                        csv_data = comp_df.to_csv(index=False)
                        st.download_button(
                            label="📥 Download upgrade analysis as CSV",
                            data=csv_data,
                            file_name=f"makemefly_upgrade_{fly_from}_{dep_str}.csv",
                            mime="text/csv",
                        )

# Yes, the 3 Diet Cokes in the footer is real. It was actually 4.
st.divider()
with st.expander("Privacy Policy"):
    privacy_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "PRIVACY.md"
    )
    try:
        with open(privacy_path, "r") as f:
            st.markdown(f.read())
    except FileNotFoundError:
        st.write("Privacy policy not found.")
st.caption(
    "Make Me Fly — Built with Claude Code + Amadeus GDS API + 3 Diet Cokes"
)
