#!/usr/bin/env python3
"""
Herfstvakantie 2026 Package Holiday Scraper
Profile:
- Party: 2 Adults + 2 Kids (ages 5 and 0) -> 4 travelers (roomAllocation=A-A-5-0)
- Board: All Inclusive (AI)
- Duration: 7 Nights (1 full week)
- Dates: Herfstvakantie 2026 (10.10.2026 - 18.10.2026 / 10.10.2026 - 25.10.2026)
- Departure Airports: Amsterdam (AMS), Düsseldorf (DUS), Cologne/Bonn (CGN)
- Destinations: Turkey, Egypt, Spain, Greece, Portugal, Cyprus
"""

import os
import re
import json
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept-Language': 'nl-NL,nl;q=0.9,de-DE,de;q=0.8,en;q=0.7',
}

DESTINATIONS = [
    ('Turkey', 'tuerkei'),
    ('Egypt', 'aegypten'),
    ('Spain', 'spanien'),
    ('Greece', 'griechenland'),
    ('Portugal', 'portugal'),
    ('Cyprus', 'zypern'),
]

AIRPORTS = ['AMS', 'DUS', 'CGN']

def build_family_url(href, ap, dates, adults=2, child_ages='5,0', nights=7, board='AI'):
    """Rebuilds Check24 URLs with strict 4-person family allocation (2 adults + 2 kids)."""
    parsed = urlparse(href)
    params = parse_qs(parsed.query, keep_blank_values=True)

    # Remove conflicting single/couple parameters
    for k in ['departureDate', 'returnDate', 'days', 'roomAllocation',
              'ab', 'airport', 'reisedauer', 'reisezeitraum', 'verpflegung',
              'erwachsene', 'kinder', 'kinderalter']:
        params.pop(k, None)

    def to_iso(d):
        p = d.strip().split('.')
        return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else d

    start, end = dates.split('-', 1) if '-' in dates else (dates, dates)

    # Force family room allocation: A-A-5-0
    alloc = 'A-' * adults + '-'.join(str(a).strip() for a in child_ages.split(','))

    params['airport'] = [ap]
    params['roomAllocation'] = [alloc]
    params['departureDate'] = [to_iso(start)]
    params['returnDate'] = [to_iso(end)]
    params['days'] = [str(nights)]
    params['verpflegung'] = [board]

    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))

def scrape_herfstvakantie(
    airports=AIRPORTS,
    dates='10.10.2026-18.10.2026',
    adults=2,
    child_ages='5,0',
    nights=7,
    board='AI'
):
    all_results = []
    n_people = adults + len(child_ages.split(',')) if child_ages else adults

    print(f"==================================================================")
    print(f"Scraping Herfstvakantie 2026 Packages")
    print(f"Party: {adults} Adults + Kids ({child_ages}) = {n_people} Travelers (Family Allocation: A-A-{child_ages.replace(',', '-')})")
    print(f"Duration: {nights} Nights | Board: All Inclusive")
    print(f"Dates: {dates} | Airports: {', '.join(airports)}")
    print(f"==================================================================\n")

    for ap in airports:
        for dest_name, slug in DESTINATIONS:
            url = (
                f"https://urlaub.check24.de/pauschalreisen/{slug}"
                f"?ab={ap}&reisedauer={nights}&reisezeitraum={dates}"
                f"&verpflegung={board}&roomAllocation=A-A-{child_ages.replace(',', '-')}"
            )
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                soup = BeautifulSoup(r.text, 'html.parser')

                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if not ('/hotel/' in href or 'angebot' in href):
                        continue

                    card = a.find_parent(['div', 'article', 'li'])
                    if not card:
                        continue

                    text = card.get_text(' ', strip=True)
                    if 'ab ' not in text or '€' not in text:
                        continue

                    # Filter specifically for 7-night / 1-week packages
                    is_week = ('1 woche' in text.lower() or '7 tage' in text.lower() or '7 nächte' in text.lower())

                    m_price = re.search(r'ab\s+([\d.]+)\s*€', text)
                    if not m_price:
                        continue
                    price = int(m_price.group(1).replace('.', ''))
                    if not (350 <= price <= 15000):
                        continue

                    # Extract hotel name
                    title_el = card.find(['h2', 'h3', 'h4', 'strong'])
                    title = title_el.get_text(strip=True) if title_el else ''
                    if not title or len(title) < 4 or any(k in title for k in ['Pauschal', 'Filter', 'Karte', 'Bewertung', 'Flug', 'Top-Service']):
                        m_hotel = re.match(r'^([^0-9\n\r]+?)(?:\s+(?:Direkte Strandlage|Top Bewertung|Hotel inkl\.|Pauschalreise|1 Woche|\d Tage|\d,\d))', text)
                        title = m_hotel.group(1).strip() if m_hotel else text.split(',')[0].strip()

                    if len(title) < 4 or any(k in title for k in ['Pauschal', 'Filter', 'Karte']):
                        continue

                    raw_url = href if href.startswith('http') else 'https://urlaub.check24.de' + href

                    # Build explicit 4-person URL
                    family_url = build_family_url(
                        raw_url,
                        ap=ap,
                        dates=dates,
                        adults=adults,
                        child_ages=child_ages,
                        nights=nights,
                        board=board
                    )

                    all_results.append({
                        'airport': ap,
                        'destination': dest_name,
                        'hotel': title,
                        'price_total_eur': price,
                        'price_per_person': round(price / n_people),
                        'nights': nights,
                        'is_confirmed_week': is_week,
                        'board': 'All Inclusive',
                        'party': f'{adults} Adults + 2 Kids ({child_ages}) [4 Persons]',
                        'roomAllocation': f'A-A-{child_ages.replace(",", "-")}',
                        'dates': dates,
                        'url': family_url,
                        'snippet': text[:140]
                    })
            except Exception as e:
                print(f"Error scraping {ap} - {dest_name}: {e}")

    # Deduplicate prioritizing 1-week matches & lowest price
    seen = {}
    for r in all_results:
        key = (r['airport'], r['destination'], r['hotel'][:15].lower())
        if key not in seen:
            seen[key] = r
        else:
            if r['is_confirmed_week'] and not seen[key]['is_confirmed_week']:
                seen[key] = r
            elif r['price_total_eur'] < seen[key]['price_total_eur']:
                seen[key] = r

    dedup = sorted(seen.values(), key=lambda x: (not x['is_confirmed_week'], x['price_total_eur']))
    return dedup

def run():
    deals_exact = scrape_herfstvakantie(dates='10.10.2026-18.10.2026')

    out_paths = [
        '/data/data/com.termux/files/home/holidays/herfstvakantie_deals.json',
        '/root/herfstvakantie_deals.json',
        '/root/fresh_10_18_oct_scrape.json'
    ]

    for p in out_paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as f:
                json.dump(deals_exact, f, indent=2)
        except Exception as e:
            print(f"Error saving to {p}: {e}")

    print(f"\nDone! Scraped {len(deals_exact)} total packages.")
    
    week_deals = [d for d in deals_exact if d['is_confirmed_week']]
    print(f"Confirmed 1-week (7 nights) family deals: {len(week_deals)}\n")

    by_dest = {}
    for d in week_deals:
        by_dest.setdefault(d['destination'], []).append(d)

    for dest, items in by_dest.items():
        print(f"=================== {dest.upper()} ===================")
        for d in sorted(items, key=lambda x: x['price_total_eur'])[:6]:
            print(f"* [{d['airport']}] {d['hotel']}")
            print(f"  Total: €{d['price_total_eur']} (~€{d['price_per_person']}/person) | 7 Nights All-Inclusive")
            print(f"  Party: {d['party']}")
            print(f"  Link: {d['url']}")
        print()

if __name__ == '__main__':
    run()
