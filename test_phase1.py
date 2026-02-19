"""
Phase 1 test: Discover destinations from YVR, then get business class pricing
for the top 5 cheapest.
"""
import time
from flight_finder import discover_destinations, search_flights

ORIGIN = "YVR"
TOP_N = 5
DEPARTURE = "2026-03-15"
RETURN = "2026-03-22"

# Step 1: Discover destinations from YVR
print(f"=== Step 1: Discovering destinations from {ORIGIN} ===\n")
destinations = discover_destinations(origin=ORIGIN)

if not destinations:
    print("No destinations returned. Check API credentials.")
    raise SystemExit(1)

print(f"Found {len(destinations)} destinations.")

# If inspiration search returned prices, show them sorted
has_prices = "price" in destinations[0]
if has_prices:
    print(f"\nTop {TOP_N} cheapest (from Inspiration Search):\n")
    print(f"{'Dest':<6} {'Price':>8}  {'Depart':<12} {'Return':<12}")
    print("-" * 42)
    for d in destinations[:TOP_N]:
        print(f"{d['destination']:<6} ${float(d['price']['total']):>7,.0f}  "
              f"{d.get('departureDate', 'N/A'):<12} {d.get('returnDate', 'N/A'):<12}")
else:
    print(f"Using direct destinations fallback (no pre-sorted prices).")
    print(f"First {TOP_N}: {', '.join(d['destination'] for d in destinations[:TOP_N])}")

# Step 2: Business class pricing for top 5
print(f"\n\n=== Step 2: Business Class Pricing — {ORIGIN} → Top {TOP_N} ===\n")

results = []
for dest_info in destinations[:TOP_N]:
    dest = dest_info["destination"]
    dep = dest_info.get("departureDate", DEPARTURE)
    ret = dest_info.get("returnDate", RETURN)

    print(f"Searching {ORIGIN} → {dest} ({dep} to {ret})...", end=" ", flush=True)

    flights = search_flights(
        origin=ORIGIN,
        destination=dest,
        departure_date=dep,
        return_date=ret,
        cabin="BUSINESS",
        max_results=3,
        currency="CAD",
    )

    if not flights:
        print("no results")
        continue

    cheapest = flights[0]
    price = float(cheapest["price"]["grandTotal"])
    print(f"${price:,.0f} CAD")

    for i, f in enumerate(flights, 1):
        p = float(f["price"]["grandTotal"])
        itinerary = f["itineraries"][0]
        segments = itinerary["segments"]
        stops = len(segments) - 1
        carriers = ", ".join(sorted(set(s["carrierCode"] for s in segments)))
        duration = itinerary.get("duration", "").replace("PT", "")
        route = " → ".join(
            [segments[0]["departure"]["iataCode"]]
            + [s["arrival"]["iataCode"] for s in segments]
        )
        dep_time = segments[0]["departure"]["at"]

        results.append({
            "dest": dest,
            "price": p,
            "carriers": carriers,
            "stops": stops,
            "duration": duration,
            "route": route,
            "depart": dep_time,
        })

    # Respect rate limit (10 req/sec)
    time.sleep(0.2)

# Summary sorted by price
print(f"\n\n=== Summary: Cheapest Business Class from {ORIGIN} ===\n")
results.sort(key=lambda x: x["price"])

print(f"{'Dest':<6} {'Price':>10}  {'Airlines':<8} {'Stops':<6} {'Duration':<10} {'Route'}")
print("-" * 75)
for r in results:
    print(f"{r['dest']:<6} ${r['price']:>9,.0f}  {r['carriers']:<8} "
          f"{r['stops']:<6} {r['duration']:<10} {r['route']}")

print(f"\n=== Phase 1 complete — {len(results)} business class options found ===")
