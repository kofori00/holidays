import requests
from bs4 import BeautifulSoup
import json
import re

session = requests.Session()
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept-Language': 'de-DE,de;q=0.9,nl;q=0.8,en;q=0.7',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': 'https://urlaub.check24.de',
}
session.headers.update(HEADERS)
session.cookies.set('c24consent', 'fam', domain='.check24.de')

HOTEL_NAME = "Rixos Sungate - The Land of Legends Access"
HOTEL_ID = 16147
AREA_ID = 580
AIRPORTS = ['AMS', 'DUS', 'CGN']
ADULTS = 2
CHILD_AGES = '5,0'
ROOM_ALLOC = f"A-A-{CHILD_AGES.replace(',', '-')}"
BOARD = 'AI'
TRAVELERS = 4

# Meivakantie window: April 15 to May 15, 2027
WIN_START = "2027-04-15"
WIN_END = "2027-05-15"

def build_booking_url(airport, dep_date, ret_date, nights):
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

results = []
seen = set()

for nights in [11, 12]:
    for ap in AIRPORTS:
        search_url = (
            f"https://urlaub.check24.de/suche/angebot"
            f"?airport={ap}&transportType=flight&roomAllocation={ROOM_ALLOC}"
            f"&departureDate={WIN_START}&returnDate={WIN_END}&days={nights}"
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

            data = r_api.json()
            raw_offers = data.get('offerData', [])

            count = 0
            for o in raw_offers:
                dep = o.get('departureDate', '')
                ret = o.get('returnDate', '')
                price = float(o.get('price', 0))
                dur = int(o.get('travelDays', o.get('travelDuration', 0)))

                if not dep or price <= 0:
                    continue
                if not (WIN_START <= dep <= WIN_END):
                    continue

                key = (ap, dep, ret, dur)
                if key in seen:
                    continue
                seen.add(key)

                url = build_booking_url(ap, dep, ret, dur)
                results.append({
                    'hotel': HOTEL_NAME,
                    'hotel_id': HOTEL_ID,
                    'region': 'Antalya / Kemer (Beldibi)',
                    'airport': ap,
                    'departure_date': dep,
                    'return_date': ret,
                    'nights': dur,
                    'board': 'All Inclusive',
                    'party': f'{ADULTS} Adults + 2 Kids ({CHILD_AGES})',
                    'price_total_eur': round(price, 2),
                    'price_per_person': round(price / TRAVELERS, 2),
                    'booking_url': url,
                })
                count += 1
            print(f"[{ap}] {nights} Nights: {count} offers")
        except Exception as e:
            print(f"[{ap}] {nights} Nights Error: {e}")

# Save results
out_file = '/data/data/com.termux/files/home/holidays/rixos_sungate_meivakantie_11_12_nights.json'
with open(out_file, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\nTotal scraped offers: {len(results)}")
print(f"Saved to: {out_file}")

# Print Top Deals by duration and airport
for nights in [11, 12]:
    print("\n" + "="*70)
    print(f"BEST DEALS: {nights} NIGHTS (MEIVAKANTIE)")
    print("="*70)
    subset = [r for r in results if r['nights'] == nights]
    for ap in AIRPORTS:
        ap_deals = [r for r in subset if r['airport'] == ap]
        if ap_deals:
            best = min(ap_deals, key=lambda x: x['price_total_eur'])
            print(f"  * [{ap}] €{best['price_total_eur']} (~€{best['price_per_person']}/p) | {best['departure_date']} -> {best['return_date']}")
            print(f"    Link: {best['booking_url']}")
