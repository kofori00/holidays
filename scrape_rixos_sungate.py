#!/usr/bin/env python3
"""
Rixos Sungate (Antalya / Kemer) Package Scraper
Settings mirrored from run_herfstvakantie_scrape.py:
- Hotel: Rixos Sungate - The Land of Legends Access (hotelId=16147, areaId=580)
- Destination: Turkey / Antalya (Beldibi / Kemer)
- Party: 2 Adults + 2 Kids (ages 5 and 0) -> 4 Travelers (roomAllocation=A-A-5-0)
- Board: All Inclusive (AI)
- Duration: 7 Nights (1 week)
- Departure Airports: AMS (Amsterdam), DUS (Düsseldorf), CGN (Cologne/Bonn)
"""

import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date

HOTEL_NAME = "Rixos Sungate - The Land of Legends Access"
HOTEL_ID = 16147
AREA_ID = 580
AIRPORTS = ['AMS', 'DUS', 'CGN']
ADULTS = 2
CHILD_AGES = '5,0'
ROOM_ALLOC = f"A-A-{CHILD_AGES.replace(',', '-')}"
BOARD = 'AI'
NIGHTS = 7
TRAVELERS = 4

WINDOWS = [
    ("Herfstvakantie (Autumn Break)", "2027-10-01", "2027-10-31"),
    ("Meivakantie (May / Spring Break)", "2027-04-15", "2027-05-15"),
    ("Zomervakantie (Summer Peak)", "2027-07-01", "2027-08-31"),
    ("Early Summer (June Deals)", "2027-06-01", "2027-06-30"),
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept-Language': 'de-DE,de;q=0.9,nl;q=0.8,en;q=0.7',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': 'https://urlaub.check24.de',
}

def build_booking_url(airport, dep_date, ret_date, nights=7):
    # Formats ISO date to German date DD.MM.YYYY for display / query
    d_parts = dep_date.split('-')
    r_parts = ret_date.split('-')
    dep_de = f"{d_parts[2]}.{d_parts[1]}.{d_parts[0]}" if len(d_parts) == 3 else dep_date
    ret_de = f"{r_parts[2]}.{r_parts[1]}.{r_parts[0]}" if len(r_parts) == 3 else ret_date
    
    return (
        f"https://urlaub.check24.de/suche/angebot"
        f"?airport={airport}&transportType=flight&roomAllocation={ROOM_ALLOC}"
        f"&departureDate={dep_date}&returnDate={ret_date}&days={nights}"
        f"&page=1&pageArea=package&areaId={AREA_ID}&hotelId={HOTEL_ID}"
        f"&offerSort=default&verpflegung={BOARD}&ab={airport}"
        f"&reisezeitraum={dep_de}-{ret_de}"
    )

def run_scrape():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set('c24consent', 'fam', domain='.check24.de')

    print("==================================================================")
    print(f"Scraping: {HOTEL_NAME}")
    print(f"Destination: Antalya / Kemer (Beldibi), Turkey")
    print(f"Party: {ADULTS} Adults + 2 Kids ({CHILD_AGES}) = {TRAVELERS} Travelers ({ROOM_ALLOC})")
    print(f"Duration: {NIGHTS} Nights | Board: All Inclusive (AI)")
    print(f"Airports: {', '.join(AIRPORTS)}")
    print("==================================================================\n")

    all_deals = []
    seen = set()

    for season_name, win_start, win_end in WINDOWS:
        print(f"\n--- Checking {season_name} ({win_start} to {win_end}) ---")
        
        for ap in AIRPORTS:
            search_url = (
                f"https://urlaub.check24.de/suche/angebot"
                f"?airport={ap}&transportType=flight&roomAllocation={ROOM_ALLOC}"
                f"&departureDate={win_start}&returnDate={win_end}&days={NIGHTS}"
                f"&pageArea=package&areaId={AREA_ID}&hotelId={HOTEL_ID}"
                f"&offerSort=default&verpflegung={BOARD}"
            )

            try:
                r_page = session.get(search_url, timeout=20)
                soup = BeautifulSoup(r_page.text, 'html.parser')
                client_id = ""
                for s in soup.find_all('script'):
                    st = s.string or ''
                    m = re.search(r'"clientId"\s*:\s*"([^"]+)"', st)
                    if m:
                        client_id = m.group(1)
                        break

                post_data = {
                    'searchUrl': search_url,
                    'completeResult': '1',
                    'clientId': client_id,
                    'initialCall': '1',
                }

                r_api = session.post(
                    "https://urlaub.check24.de/suche/json/offer/price-calendar",
                    data=post_data,
                    headers={'Referer': search_url},
                    timeout=30
                )

                if r_api.status_code != 200:
                    print(f"  [{ap}] API returned status {r_api.status_code}")
                    continue

                data = r_api.json()
                raw_offers = data.get('offerData', [])
                
                ap_matches = 0
                for o in raw_offers:
                    dep = o.get('departureDate', '')
                    ret = o.get('returnDate', '')
                    price = float(o.get('price', 0))
                    dur = int(o.get('travelDays', o.get('travelDuration', 0)))

                    if not dep or price <= 0:
                        continue

                    # Filter within window
                    if not (win_start <= dep <= win_end):
                        continue

                    key = (ap, dep, ret, dur)
                    if key in seen:
                        continue
                    seen.add(key)

                    booking_link = build_booking_url(ap, dep, ret, nights=dur)

                    deal_entry = {
                        'hotel': HOTEL_NAME,
                        'hotel_id': HOTEL_ID,
                        'region': 'Antalya / Kemer (Beldibi)',
                        'country': 'Turkey',
                        'airport': ap,
                        'season': season_name,
                        'departure_date': dep,
                        'return_date': ret,
                        'nights': dur,
                        'board': 'All Inclusive',
                        'party': f'{ADULTS} Adults + 2 Kids ({CHILD_AGES}) [{TRAVELERS} Persons]',
                        'roomAllocation': ROOM_ALLOC,
                        'price_total_eur': round(price, 2),
                        'price_per_person': round(price / TRAVELERS, 2),
                        'booking_url': booking_link,
                    }
                    all_deals.append(deal_entry)
                    ap_matches += 1

                print(f"  [{ap}] Found {ap_matches} matching 7-night offers in {season_name}")

            except Exception as e:
                print(f"  [{ap}] Error: {e}")

    # Sort deals by price
    all_deals.sort(key=lambda x: x['price_total_eur'])

    # Save to disk
    out_paths = [
        '/data/data/com.termux/files/home/holidays/rixos_sungate_deals.json',
        '/root/rixos_sungate_deals.json',
    ]

    for p in out_paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as f:
                json.dump(all_deals, f, indent=2)
            print(f"Saved {len(all_deals)} deals to {p}")
        except Exception as e:
            print(f"Error saving to {p}: {e}")

    # Print summary highlights
    print("\n" + "=" * 70)
    print("TOP CHEAPEST OFFERS ACROSS ALL SEASONS & AIRPORTS")
    print("=" * 70)
    for d in all_deals[:10]:
        print(f"* [{d['airport']}] {d['departure_date']} -> {d['return_date']} ({d['nights']} days, {d['season']})")
        print(f"  Total: €{d['price_total_eur']} (~€{d['price_per_person']}/person) | All Inclusive")
        print(f"  Link: {d['booking_url']}\n")

    # Group by season
    by_season = {}
    for d in all_deals:
        by_season.setdefault(d['season'], []).append(d)

    for season, items in by_season.items():
        print("=" * 70)
        print(f"BEST DEALS: {season.upper()}")
        print("=" * 70)
        for ap in AIRPORTS:
            ap_items = [x for x in items if x['airport'] == ap]
            if ap_items:
                cheapest_ap = min(ap_items, key=lambda x: x['price_total_eur'])
                print(f"  [{ap}] Best: €{cheapest_ap['price_total_eur']} (~€{cheapest_ap['price_per_person']}/p) on {cheapest_ap['departure_date']}")
                print(f"       Link: {cheapest_ap['booking_url']}")
        print()

if __name__ == '__main__':
    run_scrape()
