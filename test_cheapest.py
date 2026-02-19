"""
Scan a wider set of popular destinations from YVR to find the cheapest
business class fares. Uses the direct destinations list but picks a diverse
mix of short/medium/long haul routes.
"""
import time
from flight_finder import get_direct_destinations, search_flights

ORIGIN = "YVR"
DEPARTURE = "2026-03-15"
RETURN = "2026-03-22"

# Get all direct destinations
all_dests = get_direct_destinations(ORIGIN)
print(f"YVR has {len(all_dests)} direct destinations.\n")

# Pick a diverse set of ~20 popular destinations to scan
scan_dests = [
    "LAX", "SFO", "SEA", "PDX", "LAS",   # US West
    "DEN", "ORD", "YYZ", "YUL", "YYC",    # US/Canada
    "NRT", "HND", "ICN", "HKG", "TPE",    # Asia
    "LHR", "CDG", "FRA",                   # Europe
    "HNL", "CUN", "MEX", "SJD",           # Leisure
]
# Only scan codes that are actually direct destinations
scan_dests = [d for d in scan_dests if d in all_dests]
print(f"Scanning {len(scan_dests)} destinations: {', '.join(scan_dests)}\n")

results = []
for dest in scan_dests:
    try:
        flights = search_flights(
            origin=ORIGIN,
            destination=dest,
            departure_date=DEPARTURE,
            return_date=RETURN,
            cabin="BUSINESS",
            max_results=1,
            currency="CAD",
        )
        if flights:
            f = flights[0]
            price = float(f["price"]["grandTotal"])
            segments = f["itineraries"][0]["segments"]
            stops = len(segments) - 1
            carriers = ", ".join(sorted(set(s["carrierCode"] for s in segments)))
            duration = f["itineraries"][0].get("duration", "").replace("PT", "")
            results.append({
                "dest": dest,
                "price": price,
                "carriers": carriers,
                "stops": stops,
                "duration": duration,
            })
            print(f"  {dest}: ${price:,.0f} CAD ({carriers}, {stops} stop{'s' if stops != 1 else ''}, {duration})")
        else:
            print(f"  {dest}: no results")
    except Exception as e:
        print(f"  {dest}: error — {e}")
    time.sleep(0.15)

# Sort by price and show top 5
print(f"\n\n=== Top 5 Cheapest Business Class from {ORIGIN} (round-trip, {DEPARTURE} to {RETURN}) ===\n")
results.sort(key=lambda x: x["price"])
print(f"{'#':<4} {'Dest':<6} {'Price':>10}  {'Airlines':<8} {'Stops':<6} {'Duration'}")
print("-" * 55)
for i, r in enumerate(results[:5], 1):
    print(f"{i:<4} {r['dest']:<6} ${r['price']:>9,.0f}  {r['carriers']:<8} {r['stops']:<6} {r['duration']}")
