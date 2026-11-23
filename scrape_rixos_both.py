#!/usr/bin/env python3
"""
Side-by-side Live Scraper for:
1. Rixos Premium Belek - The Land of Legends Access (hotelId=14852, areaId=578)
2. Rixos Sungate - The Land of Legends Access (hotelId=16147, areaId=580)

Uses the exact saved family configurations from:
- scrape_rixos_sungate.py (7 nights across 4 saved 2027 windows)
- scrape_rixos_meivakantie.py (11 & 12 nights during Meivakantie 2027)

Profile:
- Party: 2 Adults + 2 Kids (ages 5 and 0) -> 4 Travelers (roomAllocation=A-A-5-0)
- Board: All Inclusive (AI)
- Departure Airports: AMS (Amsterdam), DUS (Düsseldorf), CGN (Cologne/Bonn)
"""

import os
import re
import json
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

BASE_DIR = "/data/data/com.termux/files/home/holidays"

HOTELS = [
    {
        "key": "rixos_premium_belek",
        "name": "Rixos Premium Belek - The Land of Legends Access",
        "hotel_id": 14852,
        "area_id": 578,
        "region": "Antalya / Belek",
        "out_7n": os.path.join(BASE_DIR, "rixos_premium_belek_deals.json"),
        "out_mei": os.path.join(BASE_DIR, "rixos_premium_belek_meivakantie_11_12_nights.json"),
    },
    {
        "key": "rixos_sungate",
        "name": "Rixos Sungate - The Land of Legends Access",
        "hotel_id": 16147,
        "area_id": 580,
        "region": "Antalya / Kemer (Beldibi)",
        "out_7n": os.path.join(BASE_DIR, "rixos_sungate_deals.json"),
        "out_mei": os.path.join(BASE_DIR, "rixos_sungate_meivakantie_11_12_nights.json"),
    },
]

AIRPORTS = ["AMS", "DUS", "CGN"]
ADULTS = 2
CHILD_AGES = "5,0"
ROOM_ALLOC = f"A-A-{CHILD_AGES.replace(',', '-')}"
BOARD = "AI"
TRAVELERS = 4

WINDOWS_7N = [
    ("Meivakantie (May / Spring Break)", "2027-04-15", "2027-05-15"),
    ("Early Summer (June Deals)", "2027-06-01", "2027-06-30"),
    ("Zomervakantie (Summer Peak)", "2027-07-01", "2027-08-31"),
    ("Herfstvakantie (Autumn Break)", "2027-10-01", "2027-10-31"),
]

MEI_START = "2027-04-15"
MEI_END = "2027-05-15"
MEI_LONG_NIGHTS = [11, 12]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,nl;q=0.8,en;q=0.7",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://urlaub.check24.de",
}


def build_booking_url(hotel_id, area_id, airport, dep_date, ret_date, nights):
    d_parts = dep_date.split("-")
    r_parts = ret_date.split("-")
    dep_de = f"{d_parts[2]}.{d_parts[1]}.{d_parts[0]}" if len(d_parts) == 3 else dep_date
    ret_de = f"{r_parts[2]}.{r_parts[1]}.{r_parts[0]}" if len(r_parts) == 3 else ret_date
    return (
        f"https://urlaub.check24.de/suche/angebot"
        f"?airport={airport}&transportType=flight&roomAllocation={ROOM_ALLOC}"
        f"&departureDate={dep_date}&returnDate={ret_date}&days={nights}"
        f"&page=1&pageArea=package&areaId={area_id}&hotelId={hotel_id}"
        f"&offerSort=default&verpflegung={BOARD}&ab={airport}"
        f"&reisezeitraum={dep_de}-{ret_de}"
    )


def fetch_calendar(session, hotel, airport, win_start, win_end, nights):
    search_url = (
        f"https://urlaub.check24.de/suche/angebot"
        f"?airport={airport}&transportType=flight&roomAllocation={ROOM_ALLOC}"
        f"&departureDate={win_start}&returnDate={win_end}&days={nights}"
        f"&pageArea=package&areaId={hotel['area_id']}&hotelId={hotel['hotel_id']}"
        f"&offerSort=default&verpflegung={BOARD}"
    )
    r_page = session.get(search_url, timeout=25)
    soup = BeautifulSoup(r_page.text, "html.parser")
    page_title = soup.title.string.strip() if soup.title and soup.title.string else ""

    client_id = ""
    for s in soup.find_all("script"):
        st = s.string or ""
        m = re.search(r'"clientId"\s*:\s*"([^"]+)"', st)
        if m:
            client_id = m.group(1)
            break

    post_data = {
        "searchUrl": search_url,
        "completeResult": "1",
        "clientId": client_id,
        "initialCall": "1",
    }

    r_api = session.post(
        "https://urlaub.check24.de/suche/json/offer/price-calendar",
        data=post_data,
        headers={"Referer": search_url},
        timeout=30,
    )
    return r_page.status_code, r_api.status_code, page_title, (r_api.json() if r_api.status_code == 200 else {})


def scrape_hotel(hotel):
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set("c24consent", "fam", domain=".check24.de")

    deals_7n = []
    seen_7n = set()
    deals_mei = []
    seen_mei = set()
    verified_title = None
    errors = []

    print(f"\n[{hotel['key']}] Starting scrape: {hotel['name']} (hotelId={hotel['hotel_id']}, areaId={hotel['area_id']})", flush=True)

    # 1. 7-night windows
    for season_name, win_start, win_end in WINDOWS_7N:
        for ap in AIRPORTS:
            try:
                p_code, a_code, title, data = fetch_calendar(session, hotel, ap, win_start, win_end, 7)
                if not verified_title and title:
                    verified_title = title
                    print(f"[{hotel['key']}] Verified Check24 page title: {verified_title}", flush=True)
                if a_code != 200:
                    msg = f"{season_name} [{ap}] 7N API status {a_code}"
                    errors.append(msg)
                    print(f"  [{hotel['key']}] {msg}", flush=True)
                    continue

                raw_offers = data.get("offerData", [])
                ap_matches = 0
                for o in raw_offers:
                    dep = o.get("departureDate", "")
                    ret = o.get("returnDate", "")
                    price = float(o.get("price", 0))
                    dur = int(o.get("travelDays", o.get("travelDuration", 0)))
                    if not dep or price <= 0 or not (win_start <= dep <= win_end):
                        continue
                    key = (ap, dep, ret, dur)
                    if key in seen_7n:
                        continue
                    seen_7n.add(key)
                    deals_7n.append({
                        "hotel": hotel["name"],
                        "hotel_id": hotel["hotel_id"],
                        "area_id": hotel["area_id"],
                        "region": hotel["region"],
                        "country": "Turkey",
                        "airport": ap,
                        "season": season_name,
                        "departure_date": dep,
                        "return_date": ret,
                        "nights": dur,
                        "board": "All Inclusive",
                        "party": f"{ADULTS} Adults + 2 Kids ({CHILD_AGES}) [{TRAVELERS} Persons]",
                        "roomAllocation": ROOM_ALLOC,
                        "price_total_eur": round(price, 2),
                        "price_per_person": round(price / TRAVELERS, 2),
                        "booking_url": build_booking_url(hotel["hotel_id"], hotel["area_id"], ap, dep, ret, dur),
                    })
                    ap_matches += 1
                print(f"  [{hotel['key']}] {season_name} [{ap}] 7N -> {ap_matches} offers", flush=True)
            except Exception as e:
                msg = f"{season_name} [{ap}] 7N Error: {e}"
                errors.append(msg)
                print(f"  [{hotel['key']}] {msg}", flush=True)

    # 2. Meivakantie 11 & 12 nights
    for nights in MEI_LONG_NIGHTS:
        for ap in AIRPORTS:
            try:
                p_code, a_code, title, data = fetch_calendar(session, hotel, ap, MEI_START, MEI_END, nights)
                if a_code != 200:
                    msg = f"Meivakantie [{ap}] {nights}N API status {a_code}"
                    errors.append(msg)
                    print(f"  [{hotel['key']}] {msg}", flush=True)
                    continue

                raw_offers = data.get("offerData", [])
                ap_matches = 0
                for o in raw_offers:
                    dep = o.get("departureDate", "")
                    ret = o.get("returnDate", "")
                    price = float(o.get("price", 0))
                    dur = int(o.get("travelDays", o.get("travelDuration", 0)))
                    if not dep or price <= 0 or not (MEI_START <= dep <= MEI_END):
                        continue
                    key = (ap, dep, ret, dur)
                    if key in seen_mei:
                        continue
                    seen_mei.add(key)
                    deals_mei.append({
                        "hotel": hotel["name"],
                        "hotel_id": hotel["hotel_id"],
                        "area_id": hotel["area_id"],
                        "region": hotel["region"],
                        "country": "Turkey",
                        "airport": ap,
                        "season": "Meivakantie (May / Spring Break)",
                        "departure_date": dep,
                        "return_date": ret,
                        "nights": dur,
                        "board": "All Inclusive",
                        "party": f"{ADULTS} Adults + 2 Kids ({CHILD_AGES}) [{TRAVELERS} Persons]",
                        "roomAllocation": ROOM_ALLOC,
                        "price_total_eur": round(price, 2),
                        "price_per_person": round(price / TRAVELERS, 2),
                        "booking_url": build_booking_url(hotel["hotel_id"], hotel["area_id"], ap, dep, ret, dur),
                    })
                    ap_matches += 1
                print(f"  [{hotel['key']}] Meivakantie [{ap}] {nights}N -> {ap_matches} offers", flush=True)
            except Exception as e:
                msg = f"Meivakantie [{ap}] {nights}N Error: {e}"
                errors.append(msg)
                print(f"  [{hotel['key']}] {msg}", flush=True)

    deals_7n.sort(key=lambda x: x["price_total_eur"])
    deals_mei.sort(key=lambda x: x["price_total_eur"])

    with open(hotel["out_7n"], "w") as f:
        json.dump(deals_7n, f, indent=2)
    with open(hotel["out_mei"], "w") as f:
        json.dump(deals_mei, f, indent=2)

    return {
        "hotel": hotel,
        "verified_title": verified_title,
        "deals_7n": deals_7n,
        "deals_mei": deals_mei,
        "errors": errors,
    }


def main():
    started_at = datetime.now(timezone.utc).isoformat()
    print("=" * 72)
    print(f"LIVE RIXOS COMPARISON SCRAPE | UTC: {started_at}")
    print(f"Party: {ADULTS} Adults + 2 Kids ({CHILD_AGES}) = {TRAVELERS} Travelers ({ROOM_ALLOC})")
    print(f"Board: All Inclusive ({BOARD}) | Airports: {', '.join(AIRPORTS)}")
    print("=" * 72, flush=True)

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(scrape_hotel, HOTELS))

    finished_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "config": {
            "adults": ADULTS,
            "child_ages": CHILD_AGES,
            "roomAllocation": ROOM_ALLOC,
            "board": BOARD,
            "airports": AIRPORTS,
            "windows_7n": WINDOWS_7N,
            "meivakantie_long_nights": MEI_LONG_NIGHTS,
        },
        "hotels": {},
    }

    for res in results:
        h = res["hotel"]
        summary["hotels"][h["key"]] = {
            "name": h["name"],
            "hotel_id": h["hotel_id"],
            "area_id": h["area_id"],
            "verified_page_title": res["verified_title"],
            "count_7n": len(res["deals_7n"]),
            "count_mei_11_12n": len(res["deals_mei"]),
            "errors": res["errors"],
            "out_7n": h["out_7n"],
            "out_mei": h["out_mei"],
        }

    summary_path = os.path.join(BASE_DIR, "rixos_comparison_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Print comprehensive summary
    print("\n" + "=" * 72)
    print("SUMMARY BY HOTEL, SEASON & AIRPORT (7 NIGHTS)")
    print("=" * 72)
    for res in results:
        h = res["hotel"]
        print(f"\n>>> {h['name']} (Verified: {res['verified_title']})")
        print(f"    7N offers: {len(res['deals_7n'])} | Mei 11-12N offers: {len(res['deals_mei'])} | Errors: {len(res['errors'])}")
        for season_name, _, _ in WINDOWS_7N:
            s_items = [d for d in res["deals_7n"] if d["season"] == season_name]
            print(f"  -- {season_name} ({len(s_items)} offers) --")
            for ap in AIRPORTS:
                ap_items = [d for d in s_items if d["airport"] == ap]
                if ap_items:
                    best = min(ap_items, key=lambda x: x["price_total_eur"])
                    print(f"     [{ap}] €{best['price_total_eur']:,.2f} (€{best['price_per_person']:,.2f}/p) | {best['departure_date']} -> {best['return_date']} ({best['nights']}n)")
                    print(f"          {best['booking_url']}")
                else:
                    print(f"     [{ap}] No offers")

        print(f"  -- Meivakantie 11 & 12 Nights ({len(res['deals_mei'])} offers) --")
        for n in MEI_LONG_NIGHTS:
            n_items = [d for d in res["deals_mei"] if d["nights"] == n]
            print(f"    *{n} Nights ({len(n_items)} offers)*")
            for ap in AIRPORTS:
                ap_items = [d for d in n_items if d["airport"] == ap]
                if ap_items:
                    best = min(ap_items, key=lambda x: x["price_total_eur"])
                    print(f"     [{ap}] €{best['price_total_eur']:,.2f} (€{best['price_per_person']:,.2f}/p) | {best['departure_date']} -> {best['return_date']} ({best['nights']}n)")
                    print(f"          {best['booking_url']}")
                else:
                    print(f"     [{ap}] No offers")

    print(f"\nSaved summary to {summary_path}")


if __name__ == "__main__":
    main()
