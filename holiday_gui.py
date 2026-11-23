#!/usr/bin/env python3
"""Holiday Finder GUI — clicks into Check24 hotel pages for real dates/prices"""
import asyncio, json, re, urllib.request
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from flask import Flask, render_template_string, request, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)
VLLM = "http://localhost:8080/v1/chat/completions"

def qwen_no_think(prompt, max_tokens=1500):
    body = json.dumps({
        "model": "gpt-5.5",
        "messages": [{"role": "user", "content": "/no_think\n" + prompt}],
        "max_tokens": max_tokens, "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": False}
    }).encode()
    req = urllib.request.Request(VLLM, data=body,
          headers={"Content-Type": "application/json", "Authorization": "Bearer none"})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return r["choices"][0]["message"]["content"]

async def accept_cookies(page):
    # "geht klar" is an <a> link, not a <button> — use JS evaluation
    clicked = await page.evaluate("""() => {
        const el = [...document.querySelectorAll('a,button,span')]
            .find(e => e.textContent.trim().includes('geht klar') || e.textContent.trim().includes('Alle akzeptieren'));
        if (el) { el.click(); return true; }
        return false;
    }""")
    if clicked:
        await page.wait_for_timeout(1500)

C24_CONSENT_COOKIE = {
    'name': 'c24consent', 'value': 'fam',
    'domain': '.check24.de', 'path': '/',
    'httpOnly': False, 'secure': False, 'sameSite': 'Lax'
}

async def get_hotel_links(page):
    """Extract hotel detail page links from the Check24 listing DOM"""
    return await page.evaluate("""() => {
        const seen = new Set();
        const results = [];
        const sels = [
            'a[href*="/pauschalreisen/hotel"]',
            '[class*="result"] a[href]',
            '[class*="offer"] a[href]',
            '[class*="card"] a[href]',
            'article a[href]',
        ];
        for (const sel of sels) {
            for (const a of document.querySelectorAll(sel)) {
                const href = a.href;
                if (!href || seen.has(href) || !href.includes('check24')) continue;
                seen.add(href);
                const card = a.closest('article,[class*="item"],[class*="card"],[class*="offer"],[class*="result"]');
                const nameEl = card ? card.querySelector('h2,h3,h4,[class*="name"],[class*="title"]') : null;
                const name = (nameEl ? nameEl.textContent : a.textContent).trim().slice(0, 80);
                if (name && name.length > 4) results.push({href, name});
                if (results.length >= 8) return results;
            }
        }
        return results;
    }""")

async def dismiss_cookies(page):
    """Dismiss cookie banner via JS — 'geht klar' is an <a> not a <button>"""
    clicked = await page.evaluate("""() => {
        const el = [...document.querySelectorAll('a,button,span')]
            .find(e => e.textContent.trim().includes('geht klar') || e.textContent.trim().includes('Alle akzeptieren'));
        if (el) { el.click(); return true; }
        return false;
    }""")
    if clicked:
        await page.wait_for_timeout(1500)
        print("    Cookie dismissed via JS", flush=True)
    return clicked

MONTH_DE = {
    '01': 'Januar', '02': 'Februar', '03': 'März', '04': 'April',
    '05': 'Mai', '06': 'Juni', '07': 'Juli', '08': 'August',
    '09': 'September', '10': 'Oktober', '11': 'November', '12': 'Dezember'
}

async def parse_detail_with_qwen(page, hotel_name, dest_name, adults, child_ages, departure, nights, dates=''):
    """Parse a hotel detail page: dismiss cookies, click target month, extract offer list with Qwen"""
    packages = []
    try:
        # Step 1: dismiss cookie banner
        await dismiss_cookies(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except:
            pass
        await page.wait_for_timeout(2000)

        # Step 2: click the target month in the Sparkalender to filter offers
        # dates format: "01.10.2026-31.10.2026" → "Oktober 2026"
        target_month = ''
        if dates:
            try:
                mm = dates[3:5]
                yyyy = dates[6:10]
                target_month = f"{MONTH_DE.get(mm, '')} {yyyy}"
            except:
                pass

        if target_month:
            clicked_month = await page.evaluate(f"""() => {{
                const els = [...document.querySelectorAll('a,button,span,div,td,th,li')];
                const el = els.find(e => e.textContent.trim() === '{target_month}');
                if (el) {{ el.click(); return true; }}
                // try partial match
                const el2 = els.find(e => e.textContent.trim().includes('{target_month}'));
                if (el2) {{ el2.click(); return true; }}
                return false;
            }}""")
            if clicked_month:
                print(f"    Clicked month: {target_month}", flush=True)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except:
                    pass
                await page.wait_for_timeout(3000)
            else:
                print(f"    Month {target_month} not clickable", flush=True)

        # Step 3: save debug files
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', hotel_name)[:25]
        await page.screenshot(path=f"/root/detail_loaded_{safe_name}.png")
        text = await page.evaluate("() => document.body.innerText")
        with open(f"/root/detail_loaded_{safe_name}.txt", "w") as f:
            f.write(text)

        # Step 4: find the offer list section ("Alle Angebote") and pass it to Qwen
        offer_start = text.find('Alle Angebote')
        if offer_start == -1:
            offer_start = text.find('Angebote\n')
        offer_text = text[offer_start:offer_start + 12000] if offer_start > 0 else text[:12000]

        n_people = adults + len(child_ages)
        prompt = (
            f"Extract holiday package offers from this German Check24 offer list.\n"
            f"Party: {adults} adults + children aged {child_ages} = {n_people} people total\n"
            f"Hotel: {hotel_name} | Destination: {dest_name} | Departure airport: {departure}\n"
            f"Looking for packages in: {target_month or dates}\n\n"
            f"OFFER LIST TEXT:\n{offer_text}\n\n"
            f"Each offer has: departure date (e.g. 'Do, 05.10.2026'), return date, nights, departure airport, room type, board, price in €.\n"
            f"IMPORTANT: Only extract offers departing in {target_month or dates}. Ignore June/July/August dates.\n"
            f"IMPORTANT: Prefer offers departing from {departure} (Cologne/Köln). Include others only if no {departure} offers exist.\n"
            f"Extract up to 5 offers. Return ONLY valid JSON array, no markdown:\n"
            f'[{{"hotel": "{hotel_name}", "resort": "", "destination": "{dest_name}", '
            f'"departure_date": "DD.MM.YYYY", "return_date": "DD.MM.YYYY", '
            f'"nights": 0, "price_total_eur": 0, "price_per_person": 0, '
            f'"board": "", "room_type": "", "departure_airport": ""}}]\n'
            f"If no offers found, return []"
        )
        raw = qwen_no_think(prompt)
        print(f"    Qwen raw: {raw[:400]}", flush=True)
        m = re.search(r'\[[\s\S]*?\]', raw)
        if m:
            pkgs = json.loads(m.group())
            n_people = adults + len(child_ages)
            for p in pkgs:
                if isinstance(p, dict) and p.get('departure_date') and p.get('price_total_eur', 0) > 0:
                    # Always recalculate price_per_person ourselves — never trust Qwen's figure
                    p['price_per_person'] = round(p['price_total_eur'] / max(1, n_people))
                    # Fix nights if Qwen got it wrong
                    if not p.get('nights') or p['nights'] < 2:
                        p['nights'] = nights
                    packages.append(p)
    except Exception as e:
        print(f"  Detail parse error: {e}", flush=True)
    return packages

def fallback_parse(text, dest_name, adults, child_ages):
    """Fallback: scrape starting-from prices from the listing page when no detail links found"""
    packages = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        m = re.search(r'ab\s+([\d][.\d]*)\s*€', line)
        if not m:
            continue
        try:
            price = int(m.group(1).replace('.', ''))
            if not (200 < price < 20000):
                continue
            for back in range(1, 6):
                if i - back < 0:
                    break
                c = lines[i - back].strip()
                if len(c) > 5 and not any(x in c for x in
                        ['Tage', 'Personen', 'Flug', '%', '€', 'ab ', 'Cookie', 'Nur ', 'Check']):
                    packages.append({
                        'hotel': c,
                        'resort': lines[i-back+1].strip().split(',')[0] if i-back+1 < len(lines) else dest_name,
                        'destination': dest_name,
                        'departure_date': 'Oct 2026 (cheapest in period — no specific date)',
                        'return_date': '',
                        'nights': 7,
                        'price_total_eur': price,
                        'price_per_person': round(price / max(1, adults + len(child_ages))),
                        'board': 'All Inclusive',
                        'departure_airport': 'CGN',
                        'room_type': '',
                        'note': 'Starting-from price only. Open Check24 to see exact dates.',
                    })
                    break
        except:
            pass
    seen = set()
    return sorted(
        [p for p in packages if p['hotel'] not in seen and not seen.add(p['hotel'])],
        key=lambda x: x['price_total_eur']
    )[:8]

def build_detail_url(href, departure, dates, adults, child_ages, nights, board_code):
    """Strip hotel URL's cached June-date params and replace with our actual search params."""
    parsed = urlparse(href)
    params = parse_qs(parsed.query, keep_blank_values=True)
    # Remove all date/party params that Check24 pre-fills with the cheapest offer
    for k in ['departureDate', 'returnDate', 'days', 'roomAllocation',
              'ab', 'reisedauer', 'reisezeitraum', 'verpflegung',
              'erwachsene', 'kinder', 'kinderalter']:
        params.pop(k, None)
    # Convert DD.MM.YYYY to YYYY-MM-DD for departureDate/returnDate params
    def de_to_iso(d):  # "01.10.2026" -> "2026-10-01"
        p = d.strip().split('.')
        return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else d
    start, end = dates.split('-', 1) if '-' in dates else (dates, dates)
    # Add our correct params
    params.update({
        'ab': [departure],
        'reisedauer': [str(nights)],
        'reisezeitraum': [dates],
        'verpflegung': [board_code],
        'erwachsene': [str(adults)],
        'kinder': [str(len(child_ages))],
        'kinderalter': [','.join(str(a) for a in child_ages)],
        'departureDate': [de_to_iso(start)],
        'returnDate': [de_to_iso(end)],
        'days': [str(nights)],
    })
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))

DEST_MAP = {
    'Greece': 'griechenland', 'Turkey': 'tuerkei', 'Egypt': 'aegypten',
    'Spain': 'spanien', 'Portugal': 'portugal', 'Croatia': 'kroatien',
    'Bulgaria': 'bulgarien', 'Tunisia': 'tunesien', 'Cyprus': 'zypern',
}
BOARD_MAP = {
    'All Inclusive': 'AI', 'Half Board': 'HP', 'Full Board': 'VP', 'Bed & Breakfast': 'FB'
}
BOARD_LABEL = {'AI': 'All Inclusive', 'HP': 'Half Board', 'VP': 'Full Board', 'FB': 'Bed & Breakfast'}

EXTRA_SOURCES = {
    'TUI': {
        'dest_map': {
            'Greece': 'griechenland', 'Turkey': 'tuerkei', 'Egypt': 'aegypten',
            'Spain': 'spanien', 'Portugal': 'portugal', 'Croatia': 'kroatien',
            'Tunisia': 'tunesien', 'Cyprus': 'zypern', 'Bulgaria': 'bulgarien',
        },
        'url': lambda slug, dep, dates, nights, board, adults, nc, ca:
            f"https://www.tui.com/de/pauschalreisen/{slug}/?abflughafen={dep}&reisedauer={nights}&reisezeitraum={dates}&verpflegung={board}&erwachsene={adults}&kinder={nc}&kinderalter={ca}",
        'clickthrough': True,  # navigate into hotel detail pages for real prices
    },
    'Alltours': {
        'dest_map': {
            'Greece': 'griechenland', 'Turkey': 'tuerkei', 'Egypt': 'aegypten',
            'Spain': 'spanien', 'Portugal': 'portugal', 'Croatia': 'kroatien',
            'Tunisia': 'tunesien', 'Cyprus': 'zypern', 'Bulgaria': 'bulgarien',
        },
        'url': lambda slug, dep, dates, nights, board, adults, nc, ca:
            f"https://www.alltours.de/reisen/{slug}/?abflug={dep}&dauer={nights}&zeitraum={dates}&verpflegung={board}&erwachsene={adults}&kinder={nc}&kinderalter={ca}",
    },
    'Corendon': {
        'dest_map': {
            'Greece': 'griechenland', 'Turkey': 'tuerkei', 'Egypt': 'aegypten',
            'Spain': 'spanien', 'Croatia': 'kroatien',
        },
        # Corendon uses /{dest}/ listing pages with JS filter sidebar
        'url': lambda slug, dep, dates, nights, board, adults, nc, ca:
            f"https://www.corendon.de/{slug}/",
        'corendon_filters': True,  # special filter interaction needed
    },
    'DERTOUR': {
        'dest_map': {
            'Greece': 'griechenland', 'Turkey': 'tuerkei', 'Egypt': 'aegypten',
            'Spain': 'spanien', 'Portugal': 'portugal', 'Croatia': 'kroatien',
            'Tunisia': 'tunesien', 'Cyprus': 'zypern', 'Bulgaria': 'bulgarien',
        },
        'url': lambda slug, dep, dates, nights, board, adults, nc, ca:
            f"https://www.dertour.de/pauschalreisen/{slug}/?abflughafen={dep}&reisedauer={nights}&reisezeitraum={dates}&verpflegung={board}&erwachsene={adults}&kinder={nc}&kinderalter={ca}",
    },
}

async def _accept_any_cookies(page):
    """Accept cookie banner using site-agnostic patterns."""
    clicked = await page.evaluate("""() => {
        const el = [...document.querySelectorAll('button,a,span')]
            .find(e => /akzeptieren|accepteer|accept all|alle.akzept|geht klar|Alle.zustimmen/i.test(e.textContent.trim()));
        if (el) { el.click(); return el.textContent.trim().slice(0,40); }
        return null;
    }""")
    if clicked:
        print(f"    Cookies accepted: {clicked}", flush=True)
        await page.wait_for_timeout(2000)
    return clicked

async def _click_corendon_filters(page, departure, dates, board_label):
    """Interact with Corendon's sidebar filter checkboxes."""
    # Parse month from dates "01.10.2026-31.10.2026" → "Oktober 2026"
    month_start = dates.split('-')[0]
    month_key = month_start[3:5]
    month_name = MONTH_DE.get(month_key, '')
    target_month = f"{month_name} {month_start[6:]}" if month_name else ''

    # Airport display names for Corendon sidebar
    airport_labels = {
        'CGN': 'Köln/Bonn', 'DUS': 'Düsseldorf', 'FRA': 'Frankfurt',
        'MUC': 'München', 'BER': 'Berlin-Brandenburg', 'HAM': 'Hamburg',
        'STR': 'Stuttgart', 'NUE': 'Nürnberg', 'HAJ': 'Hannover',
    }
    airport_label = airport_labels.get(departure, departure)

    board_map = {'All Inclusive': 'All inkl', 'Vollpension': 'Vollpension', 'Halbpension': 'Halbpension'}
    board_key = next((v for k, v in board_map.items() if k.lower() in board_label.lower()), None)

    async def click_checkbox_by_text(text):
        result = await page.evaluate(f"""() => {{
            const all = [...document.querySelectorAll('label,li,div')];
            const el = all.find(e => {{
                const t = e.textContent.trim();
                return t.includes({json.dumps(text)}) && (e.querySelector('input[type=checkbox]') || e.tagName === 'LABEL');
            }});
            if (el) {{
                const cb = el.querySelector('input[type=checkbox]');
                if (cb) cb.click(); else el.click();
                return 'clicked: ' + el.textContent.trim().slice(0,40);
            }}
            return null;
        }}""")
        if result:
            print(f"    Corendon filter: {result}", flush=True)
            await page.wait_for_timeout(1500)
        return result

    if target_month:
        await click_checkbox_by_text(target_month)
    await click_checkbox_by_text(airport_label)
    if board_key:
        await click_checkbox_by_text(board_key)
    await page.wait_for_timeout(3000)

async def _get_tui_hotel_links(page):
    """Extract hotel detail links from a TUI listing page."""
    return await page.evaluate("""() => {
        const seen = new Set();
        const results = [];
        for (const a of document.querySelectorAll('a[href*="/de/pauschalreisen/"]')) {
            const href = a.href;
            if (!href || seen.has(href) || href.includes('?') === false) continue;
            // Only hotel detail pages, not the listing itself
            const parts = href.split('/').filter(Boolean);
            if (parts.length < 6) continue;
            seen.add(href);
            const card = a.closest('article,[class*="item"],[class*="card"],[class*="offer"],[class*="result"]');
            const nameEl = card ? card.querySelector('h2,h3,h4,[class*="name"],[class*="title"]') : null;
            const name = (nameEl ? nameEl.textContent : a.textContent).trim().slice(0, 80);
            if (name && name.length > 3) results.push({href, name});
            if (results.length >= 6) return results;
        }
        return results;
    }""")

async def _scrape_tui_detail(page, href, name, dest_name, adults, child_ages, nights, dates, board_label, n_people, listing_url):
    """Navigate to a TUI hotel detail page and extract October offers."""
    packages = []
    try:
        print(f"  TUI clicking into: {name}", flush=True)
        await page.goto(href, wait_until='domcontentloaded', timeout=30000)
        await _accept_any_cookies(page)
        try:
            await page.wait_for_load_state('networkidle', timeout=12000)
        except:
            pass
        await page.wait_for_timeout(3000)

        # Click Oktober in the date calendar if present
        target_month = ''
        month_start = dates.split('-')[0]
        month_key = month_start[3:5]
        month_name = MONTH_DE.get(month_key, '')
        if month_name:
            target_month = f"{month_name} {month_start[6:]}"
            clicked = await page.evaluate(f"""() => {{
                const el = [...document.querySelectorAll('button,div,span,td,th,li')]
                    .find(e => e.textContent.trim().includes({json.dumps(target_month)}) ||
                               e.textContent.trim().includes({json.dumps(month_name)}));
                if (el) {{ el.click(); return true; }}
                return false;
            }}""")
            if clicked:
                await page.wait_for_timeout(2000)

        text = await page.evaluate("() => document.body.innerText")
        prompt = (
            f"Extract package holiday prices from this TUI hotel detail page.\n"
            f"Hotel: {name}, Destination: {dest_name}, Period: {dates}, Nights: {nights}, Board: {board_label}\n"
            f"Party: {adults} adults + children aged {list(child_ages)} = {n_people} people total\n"
            f"Departure airport: from the search filters\n\n"
            f"Extract up to 5 available departure dates with prices for October 2026.\n"
            f"Return ONLY a valid JSON array, each item:\n"
            f'{{"hotel":"{name}","resort":"","destination":"{dest_name}","departure_date":"DD.MM.YYYY",'
            f'"return_date":"DD.MM.YYYY","nights":{nights},"price_total_eur":0,"price_per_person":0,'
            f'"board":"{board_label}","room_type":"","departure_airport":""}}\n'
            f"Only include offers departing in October 2026 with real prices (not 0).\n\n"
            f"Page text:\n{text[:8000]}"
        )
        raw = qwen_no_think(prompt, max_tokens=1500)
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            items = json.loads(m.group())
            for pkg in items:
                if isinstance(pkg, dict) and pkg.get('price_total_eur', 0) > 0:
                    pkg['source'] = 'TUI'
                    pkg['booking_url'] = href
                    pkg['price_per_person'] = round(pkg['price_total_eur'] / max(1, n_people))
                    if not pkg.get('nights') or pkg['nights'] < 2:
                        pkg['nights'] = nights
                    if not pkg.get('hotel') or len(pkg['hotel']) < 3:
                        pkg['hotel'] = name
                    packages.append(pkg)
        print(f"    TUI {name}: {len(packages)} offers", flush=True)
    except Exception as e:
        print(f"    TUI detail error ({name}): {e}", flush=True)
    return packages

async def scrape_extra_source(source_name, dest_name, url, adults, child_ages, nights, dates, board_label, departure=''):
    """Load a non-Check24 listing page and use Qwen to extract offers from the text."""
    n_people = adults + len(child_ages)
    packages = []
    cfg = EXTRA_SOURCES.get(source_name, {})
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
                '--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled'
            ])
            ctx = await browser.new_context(
                viewport={'width': 1280, 'height': 900}, locale='de-DE',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            )
            page = await ctx.new_page()
            print(f"\n>>> {source_name}/{dest_name}: {url}", flush=True)
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            await _accept_any_cookies(page)
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except:
                pass
            await page.wait_for_timeout(3000)

            # Corendon: interact with filter sidebar
            if cfg.get('corendon_filters'):
                await _click_corendon_filters(page, departure, dates, board_label)

            # TUI: click through to hotel detail pages for real per-date prices
            if cfg.get('clickthrough') and source_name == 'TUI':
                hotel_links = await _get_tui_hotel_links(page)
                print(f"  TUI listing: {len(hotel_links)} hotel links found", flush=True)
                for link in hotel_links:
                    pkgs = await _scrape_tui_detail(
                        page, link['href'], link['name'],
                        dest_name, adults, child_ages, nights, dates, board_label, n_people, url
                    )
                    packages.extend(pkgs)
                await browser.close()
                print(f"  TUI/{dest_name}: {len(packages)} packages total", flush=True)
                return packages

            text = await page.evaluate("() => document.body.innerText")
            hotel_links_dom = []
            # Capture hotel-specific links from DOM for use as booking URLs
            hotel_links_dom = await page.evaluate("""() => {
                const seen = new Set();
                const results = [];
                const sels = [
                    'a[href*="/hotel/"]', 'a[href*="/pauschalreisen/"]',
                    'a[href*="/reisen/"]', 'a[href*="/urlaub/"]',
                    '[class*="card"] a[href]', '[class*="offer"] a[href]',
                    '[class*="result"] a[href]', 'article a[href]'
                ];
                for (const sel of sels) {
                    for (const a of document.querySelectorAll(sel)) {
                        if (!a.href || seen.has(a.href) || a.href.includes('#')) continue;
                        seen.add(a.href);
                        const card = a.closest('article,[class*="item"],[class*="card"],[class*="offer"],[class*="result"]');
                        const nameEl = card ? card.querySelector('h2,h3,h4,[class*="name"],[class*="title"]') : null;
                        const name = (nameEl ? nameEl.textContent : a.textContent).trim().slice(0, 80);
                        if (name.length > 4) results.push({href: a.href, name: name.toLowerCase()});
                        if (results.length >= 30) return results;
                    }
                }
                return results;
            }""")
            await browser.close()

        if len(text.strip()) < 200:
            print(f"  {source_name}: page too short, skipping", flush=True)
            return []

        prompt = (
            f"You are extracting package holiday offers from {source_name}'s German website.\n"
            f"Destination: {dest_name}, Period: {dates}, {nights} nights, Board: {board_label}\n"
            f"Party: {adults} adults + children aged {list(child_ages)} = {n_people} people total\n\n"
            f"Extract up to 10 package holiday offers visible on this page.\n"
            f"For each offer return a JSON object with these fields:\n"
            f'"hotel" (hotel name), "resort" (area/resort), "destination" (country), '
            f'"departure_date" (DD.MM.YYYY), "return_date" (DD.MM.YYYY), "nights" (integer), '
            f'"price_total_eur" (total price in EUR as number), "price_per_person" (per person), '
            f'"board" (board type), "room_type" (room type), "departure_airport" (IATA code)\n'
            f'Return ONLY a valid JSON array. Use 0 for unknown prices, empty string for unknown text.\n'
            f"IMPORTANT: Only include offers departing in October 2026. Ignore other months.\n\n"
            f"Page text:\n{text[:10000]}"
        )
        raw = qwen_no_think(prompt, max_tokens=2000)
        print(f"  {source_name} raw: {raw[:200]}", flush=True)
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            items = json.loads(m.group())
            for pkg in items:
                if isinstance(pkg, dict) and pkg.get('price_total_eur', 0) > 0:
                    pkg['source'] = source_name
                    # Try to match hotel name to a real DOM link; fallback to listing URL
                    hotel_lower = pkg.get('hotel', '').lower()[:15]
                    matched_url = url
                    for link in (hotel_links_dom or []):
                        if hotel_lower and hotel_lower in link['name']:
                            matched_url = link['href']
                            break
                    pkg['booking_url'] = matched_url
                    pkg['price_per_person'] = round(pkg['price_total_eur'] / max(1, n_people))
                    if not pkg.get('nights') or pkg['nights'] < 2:
                        pkg['nights'] = nights
                    packages.append(pkg)
        print(f"  {source_name}/{dest_name}: {len(packages)} packages", flush=True)
    except Exception as e:
        print(f"  {source_name} ERROR: {e}", flush=True)
    return packages

async def run_search(destinations, departure, dates, adults, children, child_ages, nights, board, luxury='', waterpark=False, sources=None):
    results = []
    board_code = BOARD_MAP.get(board, 'AI')
    child_ages_str = ','.join(str(a) for a in child_ages)

    if sources is None:
        sources = ['Check24']

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled'
        ])
        for dest_name in (destinations if 'Check24' in sources else []):
            slug = DEST_MAP.get(dest_name, dest_name.lower())
            url = (f"https://urlaub.check24.de/pauschalreisen/{slug}"
                   f"?ab={departure}&reisedauer={nights}&reisezeitraum={dates}"
                   f"&verpflegung={board_code}&erwachsene={adults}"
                   f"&kinder={len(child_ages)}&kinderalter={child_ages_str}")
            if luxury == '5star':
                url += '&sterne=5'
            elif luxury == 'luxury':
                url += '&sterne=4,5'
            if waterpark:
                url += '&highlights=Wasserpark'
            print(f"\n>>> {dest_name}: {url}", flush=True)

            ctx = await browser.new_context(
                viewport={'width': 1280, 'height': 900},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                locale='de-DE',
                extra_http_headers={'Accept-Language': 'de-DE,de;q=0.9'}
            )
            # Pre-set consent cookie so the banner never appears on any page in this context
            await ctx.add_cookies([C24_CONSENT_COOKIE])
            page = await ctx.new_page()
            await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(2000)
            await accept_cookies(page)
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except:
                pass
            await page.wait_for_timeout(3000)

            body_text = await page.evaluate("() => document.body.innerText")
            with open(f'/root/c24_{slug}.txt', 'w') as f:
                f.write(body_text)
            await page.screenshot(path=f'/root/c24_{slug}.png')

            hotel_links = await get_hotel_links(page)
            print(f"  DOM hotel links found: {len(hotel_links)}", flush=True)
            for h in hotel_links:
                print(f"    - {h['name'][:60]} | {h['href'][:80]}", flush=True)

            dest_packages = []
            if hotel_links:
                for idx, h in enumerate(hotel_links[:5]):
                    print(f"\n  Clicking into: {h['name'][:60]}", flush=True)
                    detail_url = build_detail_url(
                        h['href'], departure, dates, adults, child_ages, nights, board_code
                    )
                    print(f"    URL: ...{detail_url[-120:]}", flush=True)
                    dp = await ctx.new_page()
                    try:
                        await dp.goto(detail_url, wait_until='domcontentloaded', timeout=60000)
                        await accept_cookies(dp)
                        try:
                            await dp.wait_for_load_state('networkidle', timeout=15000)
                        except:
                            pass
                        await dp.screenshot(path=f'/root/detail_{slug}_{idx}.png')
                        pkgs = await parse_detail_with_qwen(
                            dp, h['name'], dest_name, adults, child_ages, departure, nights, dates
                        )
                        for pkg in pkgs:
                            pkg['booking_url'] = detail_url
                            pkg['source'] = 'Check24'
                        print(f"    -> {len(pkgs)} packages extracted", flush=True)
                        dest_packages.extend(pkgs)
                    except Exception as e:
                        print(f"    -> ERROR: {e}", flush=True)
                    finally:
                        await dp.close()

            if not dest_packages:
                print("  Fallback: using listing-page starting-from prices", flush=True)
                dest_packages = fallback_parse(body_text, dest_name, adults, child_ages)

            results.extend(dest_packages)
            await ctx.close()

        await browser.close()

    # Extra sources (TUI, Alltours, Corendon, DERTOUR)
    extra_srcs = [s for s in (sources or []) if s in EXTRA_SOURCES]
    board_label = BOARD_LABEL.get(board_code, board)
    for source_name in extra_srcs:
        cfg = EXTRA_SOURCES[source_name]
        for dest_name in destinations:
            slug = cfg['dest_map'].get(dest_name)
            if not slug:
                continue
            url = cfg['url'](slug, departure, dates, nights, board_code, adults, len(child_ages), child_ages_str)
            pkgs = await scrape_extra_source(source_name, dest_name, url, adults, child_ages, nights, dates, board_label, departure=departure)
            results.extend(pkgs)

    results.sort(key=lambda x: x.get('price_total_eur', 99999))
    return results


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Holiday Finder</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f4f8; }
.header { background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 2rem; text-align: center; }
.header h1 { font-size: 2rem; }
.header p { opacity: .85; margin-top: .3rem; font-size: .95rem; }
.container { max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
.form-card { background: white; border-radius: 12px; padding: 2rem; box-shadow: 0 2px 12px rgba(0,0,0,.08); margin-bottom: 1.5rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; }
.form-group { display: flex; flex-direction: column; gap: .4rem; }
.form-group label { font-weight: 600; font-size: .82rem; color: #555; text-transform: uppercase; letter-spacing: .5px; }
.form-group input, .form-group select { padding: .7rem 1rem; border: 1.5px solid #ddd; border-radius: 8px; font-size: .95rem; }
.form-group input:focus, .form-group select:focus { outline: none; border-color: #667eea; }
.destinations { grid-column: 1/-1; }
.dest-grid { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: .4rem; }
.dest-btn { padding: .4rem .9rem; border: 2px solid #ddd; border-radius: 20px; background: white; cursor: pointer; font-size: .9rem; transition: all .2s; }
.dest-btn.selected { border-color: #667eea; background: #667eea; color: white; }
.search-btn { grid-column: 1/-1; background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; padding: 1rem; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; }
.search-btn:disabled { opacity: .6; cursor: wait; }
.results { display: grid; gap: 1rem; }
.result-card { background: white; border-radius: 12px; padding: 1.4rem 1.6rem; box-shadow: 0 2px 8px rgba(0,0,0,.07); border-left: 5px solid #667eea; }
.result-card.greece { border-color: #3b82f6; }
.result-card.turkey { border-color: #ef4444; }
.result-card.egypt  { border-color: #f59e0b; }
.result-card.spain  { border-color: #f97316; }
.source-badge { display:inline-block; font-size:.72rem; padding:.15rem .5rem; border-radius:8px; font-weight:700; margin-bottom:.3rem; }
.src-check24  { background:#667eea22; color:#667eea; }
.src-tui      { background:#e8001d22; color:#c00018; }
.src-sunweb   { background:#ff6b0022; color:#cc5500; }
.src-corendon { background:#00838422; color:#006666; }
.src-dertour  { background:#00539622; color:#004080; }
.source-row   { display:flex; flex-wrap:wrap; gap:.6rem; margin-top:.4rem; }
.source-toggle { display:flex; align-items:center; gap:.4rem; font-size:.88rem; cursor:pointer; }
.hotel-name { font-size: 1.1rem; font-weight: 700; color: #1a1a2e; margin-bottom: .3rem; }
.meta { font-size: .87rem; color: #555; line-height: 1.7; }
.date-row { font-size: .95rem; font-weight: 600; color: #1a1a2e; margin: .4rem 0; }
.price-block { display: flex; align-items: baseline; gap: .6rem; margin-top: .7rem; }
.price-total { font-size: 1.9rem; font-weight: 800; color: #1a1a2e; }
.price-pp { font-size: .82rem; color: #777; }
.tag { display: inline-block; font-size: .75rem; padding: .2rem .55rem; border-radius: 10px; background: #f0f0f0; color: #555; margin: .3rem .3rem 0 0; }
.tag.ai   { background: #dcfce7; color: #166534; }
.tag.note { background: #fef9c3; color: #713f12; font-size: .72rem; }
.spinner { display: none; text-align: center; padding: 3rem; color: #667eea; font-size: 1.1rem; }
.status { font-size: .9rem; color: #667eea; margin-top: .5rem; }
.error { background: #fee2e2; color: #991b1b; padding: 1rem; border-radius: 8px; margin-top: 1rem; }
.tabs { display:flex; gap:0; margin-bottom:-1px; }
.tab-btn { padding: .7rem 1.6rem; background: #e8edf5; border: 1.5px solid #ddd; border-bottom:none; border-radius:10px 10px 0 0; cursor:pointer; font-size:.95rem; font-weight:600; color:#555; transition:all .15s; }
.tab-btn.active { background:white; color:#667eea; border-color:#ddd; }
.tab-panel { display:none; }
.tab-panel.active { display:block; }
.opt-grid { display:grid; grid-template-columns:1fr 1fr; gap:1.2rem; }
.opt-grid .full { grid-column:1/-1; }
.rank-badge { display:inline-block; width:1.6rem; height:1.6rem; border-radius:50%; background:#667eea; color:white; font-size:.75rem; font-weight:700; text-align:center; line-height:1.6rem; margin-right:.4rem; }
.rank-badge.gold   { background:#f59e0b; }
.rank-badge.silver { background:#9ca3af; }
.rank-badge.bronze { background:#b45309; }
.cheapest-table { width:100%; border-collapse:collapse; margin-top:.5rem; font-size:.9rem; }
.cheapest-table th { background:#f3f4f6; padding:.6rem .8rem; text-align:left; font-size:.78rem; text-transform:uppercase; color:#555; }
.cheapest-table td { padding:.6rem .8rem; border-top:1px solid #f0f0f0; vertical-align:middle; }
.cheapest-table tr:hover td { background:#fafbff; }
.cheapest-table .winner td { background:#f0fdf4; font-weight:600; }
</style>
</head>
<body>
<div class="header">
  <h1>Holiday Finder</h1>
  <p>Actual resort prices &amp; dates — clicks through each hotel on Check24</p>
</div>
<div class="container">
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('search')">&#128269; Find Holidays</button>
    <button class="tab-btn" onclick="switchTab('cheapest')">&#128176; Price Optimizer</button>
  </div>
  <div class="form-card" style="border-radius:0 12px 12px 12px">

  <div class="tab-panel active" id="tab-search">
    <div class="form-grid">
      <div class="form-group destinations">
        <label>Destinations</label>
        <div class="dest-grid" id="destGrid">
          <button class="dest-btn selected" onclick="toggleDest(this,'Greece')">&#127468;&#127479; Greece</button>
          <button class="dest-btn selected" onclick="toggleDest(this,'Turkey')">&#127481;&#127479; Turkey</button>
          <button class="dest-btn selected" onclick="toggleDest(this,'Egypt')">&#127466;&#127468; Egypt</button>
          <button class="dest-btn" onclick="toggleDest(this,'Spain')">&#127466;&#127480; Spain</button>
          <button class="dest-btn" onclick="toggleDest(this,'Portugal')">&#127477;&#127481; Portugal</button>
          <button class="dest-btn" onclick="toggleDest(this,'Croatia')">&#127469;&#127479; Croatia</button>
          <button class="dest-btn" onclick="toggleDest(this,'Bulgaria')">&#127463;&#127468; Bulgaria</button>
          <button class="dest-btn" onclick="toggleDest(this,'Tunisia')">&#127481;&#127475; Tunisia</button>
          <button class="dest-btn" onclick="toggleDest(this,'Cyprus')">&#127464;&#127486; Cyprus</button>
        </div>
      </div>
      <div class="form-group">
        <label>Departure Airport</label>
        <select id="departure">
          <option value="CGN">Cologne (CGN)</option>
          <option value="DUS">Dusseldorf (DUS)</option>
          <option value="FRA">Frankfurt (FRA)</option>
          <option value="AMS">Amsterdam (AMS)</option>
          <option value="LGW">London Gatwick (LGW)</option>
          <option value="LHR">London Heathrow (LHR)</option>
          <option value="MAN">Manchester (MAN)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Travel Period</label>
        <input type="text" id="dates" value="01.10.2026-31.10.2026" placeholder="DD.MM.YYYY-DD.MM.YYYY">
      </div>
      <div class="form-group">
        <label>Adults</label>
        <input type="number" id="adults" value="2" min="1" max="6">
      </div>
      <div class="form-group">
        <label>Children ages (comma-separated)</label>
        <input type="text" id="childAges" value="5,0" placeholder="e.g. 5,0 for age-5 + baby">
      </div>
      <div class="form-group">
        <label>Nights</label>
        <select id="nights">
          <option value="7" selected>7 nights</option>
          <option value="10">10 nights</option>
          <option value="14">14 nights</option>
        </select>
      </div>
      <div class="form-group">
        <label>Board Type</label>
        <select id="board">
          <option value="All Inclusive" selected>All Inclusive</option>
          <option value="Half Board">Half Board</option>
          <option value="Full Board">Full Board</option>
          <option value="Bed &amp; Breakfast">Bed &amp; Breakfast</option>
        </select>
      </div>
      <div class="form-group">
        <label>Hotel Category</label>
        <select id="luxury">
          <option value="">Any star rating</option>
          <option value="luxury">4-5&#11088; Luxury</option>
          <option value="5star">5&#11088; Only</option>
        </select>
      </div>
      <div class="form-group" style="justify-content:flex-end">
        <label>Must-have Features</label>
        <label style="font-weight:normal;text-transform:none;letter-spacing:0;font-size:.95rem;display:flex;align-items:center;gap:.5rem;cursor:pointer;margin-top:.4rem">
          <input type="checkbox" id="waterpark" style="width:1.1rem;height:1.1rem"> &#127754; Waterpark / Water Slides
        </label>
      </div>
      <div class="form-group destinations">
        <label>Travel Agencies</label>
        <div class="dest-grid">
          <button class="dest-btn selected" onclick="toggleSrc(this,'Check24')">🔵 Check24</button>
          <button class="dest-btn" onclick="toggleSrc(this,'TUI')">🔴 TUI</button>
          <button class="dest-btn" onclick="toggleSrc(this,'Alltours')">🟠 Alltours</button>
          <button class="dest-btn" onclick="toggleSrc(this,'Corendon')">🟢 Corendon</button>
          <button class="dest-btn" onclick="toggleSrc(this,'DERTOUR')">🔷 DERTOUR</button>
        </div>
      </div>
      <button class="search-btn" onclick="doSearch()" id="searchBtn">Search Holidays</button>
    </div>
    <div class="status" id="status"></div>
  </div>
  <div class="spinner" id="spinner">Searching... clicking through to hotel pages (this takes 1-3 minutes)</div>
  <div id="results"></div>

  </div><!-- end tab-search -->

  <div class="tab-panel" id="tab-cheapest">
    <h3 style="margin-bottom:1.2rem;color:#1a1a2e">Find the Cheapest Deal for a Specific Resort</h3>
    <p style="font-size:.88rem;color:#666;margin-bottom:1.4rem">Enter a hotel or resort name. The optimizer tries every combination of departure date and number of nights in your range and shows the cheapest options first.</p>
    <div class="opt-grid">
      <div class="form-group full">
        <label>Hotel / Resort Name</label>
        <input type="text" id="opt-hotel" placeholder="e.g. Riu Palace, ROBINSON Club, Steigenberger Aqua Magic" style="font-size:1rem">
      </div>
      <div class="form-group">
        <label>Destination</label>
        <select id="opt-dest">
          <option value="Greece">Greece</option>
          <option value="Turkey">Turkey</option>
          <option value="Egypt">Egypt</option>
          <option value="Spain">Spain</option>
          <option value="Portugal">Portugal</option>
          <option value="Croatia">Croatia</option>
          <option value="Tunisia">Tunisia</option>
          <option value="Cyprus">Cyprus</option>
          <option value="Bulgaria">Bulgaria</option>
        </select>
      </div>
      <div class="form-group">
        <label>Departure Airport</label>
        <select id="opt-departure">
          <option value="CGN">Cologne (CGN)</option>
          <option value="DUS">Dusseldorf (DUS)</option>
          <option value="FRA">Frankfurt (FRA)</option>
          <option value="AMS">Amsterdam (AMS)</option>
          <option value="LGW">London Gatwick (LGW)</option>
          <option value="BER">Berlin (BER)</option>
          <option value="MUC">Munich (MUC)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Date From</label>
        <input type="text" id="opt-from" value="01.10.2026" placeholder="DD.MM.YYYY">
      </div>
      <div class="form-group">
        <label>Date To</label>
        <input type="text" id="opt-to" value="31.10.2026" placeholder="DD.MM.YYYY">
      </div>
      <div class="form-group">
        <label>Min Nights</label>
        <input type="number" id="opt-nights-min" value="7" min="3" max="28">
      </div>
      <div class="form-group">
        <label>Max Nights</label>
        <input type="number" id="opt-nights-max" value="14" min="3" max="28">
      </div>
      <div class="form-group">
        <label>Adults</label>
        <input type="number" id="opt-adults" value="2" min="1" max="6">
      </div>
      <div class="form-group">
        <label>Children ages (comma-separated)</label>
        <input type="text" id="opt-childAges" value="5,0" placeholder="e.g. 5,0">
      </div>
      <div class="form-group">
        <label>Board Type</label>
        <select id="opt-board">
          <option value="All Inclusive" selected>All Inclusive</option>
          <option value="Half Board">Half Board</option>
          <option value="Full Board">Full Board</option>
          <option value="Bed &amp; Breakfast">Bed &amp; Breakfast</option>
        </select>
      </div>
      <div class="form-group">
        <label>Search Via</label>
        <select id="opt-source">
          <option value="Check24">Check24 (most accurate)</option>
          <option value="TUI">TUI</option>
          <option value="Corendon">Corendon</option>
        </select>
      </div>
      <div class="form-group" style="justify-content:flex-end">
        <button class="search-btn" style="grid-column:auto" onclick="doCheapest()" id="cheapestBtn">Find Cheapest Prices</button>
      </div>
    </div>
    <div class="status" id="opt-status"></div>
    <div class="spinner" id="opt-spinner">Searching across dates &amp; durations (2-5 minutes)...</div>
    <div id="opt-results"></div>
  </div><!-- end tab-cheapest -->

  </div><!-- end form-card -->
  <div id="results-outer"></div>
</div>
<script>
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach((b,i) => b.classList.toggle('active', ['search','cheapest'][i]===name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id==='tab-'+name));
}

let selectedDests = ['Greece','Turkey','Egypt'];
let selectedSources = ['Check24'];
function toggleDest(btn, dest) {
  btn.classList.toggle('selected');
  if (selectedDests.includes(dest)) selectedDests = selectedDests.filter(d => d !== dest);
  else selectedDests.push(dest);
}
function toggleSrc(btn, src) {
  btn.classList.toggle('selected');
  if (selectedSources.includes(src)) selectedSources = selectedSources.filter(s => s !== src);
  else selectedSources.push(src);
}
function destClass(d) {
  return {Greece:'greece', Turkey:'turkey', Egypt:'egypt', Spain:'spain'}[d] || 'other';
}
async function doSearch() {
  if (!selectedDests.length) { alert('Select at least one destination'); return; }
  if (!selectedSources.length) { alert('Select at least one travel agency'); return; }
  const btn = document.getElementById('searchBtn');
  btn.disabled = true; btn.textContent = 'Searching...';
  document.getElementById('spinner').style.display = 'block';
  document.getElementById('results').innerHTML = '';
  document.getElementById('status').textContent = 'Opening Check24 + clicking into hotel pages...';

  const childAgesRaw = document.getElementById('childAges').value.trim();
  const childAges = childAgesRaw ? childAgesRaw.split(',').map(a => parseInt(a.trim())).filter(n => !isNaN(n)) : [];

  try {
    const resp = await fetch('/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        destinations: selectedDests,
        departure: document.getElementById('departure').value,
        dates: document.getElementById('dates').value,
        adults: parseInt(document.getElementById('adults').value),
        children: childAges.length,
        child_ages: childAges,
        nights: parseInt(document.getElementById('nights').value),
        board: document.getElementById('board').value,
        luxury: document.getElementById('luxury').value,
        waterpark: document.getElementById('waterpark').checked,
        sources: selectedSources
      })
    });
    const data = await resp.json();
    document.getElementById('spinner').style.display = 'none';
    if (data.error) {
      document.getElementById('results').innerHTML = '<div class="error">' + data.error + '</div>';
    } else if (!data.results || !data.results.length) {
      document.getElementById('results').innerHTML = '<div class="error">No results found. Try different dates or destinations.</div>';
    } else {
      document.getElementById('status').textContent = 'Found ' + data.results.length + ' packages';
      const srcClass = s => ({'TUI':'src-tui','Alltours':'src-sunweb','Corendon':'src-corendon','DERTOUR':'src-dertour'}[s]||'src-check24');
      const html = data.results.map(r => `
        <div class="result-card ${destClass(r.destination)}">
          <span class="source-badge ${srcClass(r.source||'Check24')}">${r.source||'Check24'}</span>
          <div class="hotel-name">${r.hotel}</div>
          <div class="meta">&#128205; ${r.resort || r.destination} &middot; ${r.destination}</div>
          <div class="date-row">&#128197; ${r.departure_date || 'Date TBC'}${r.return_date ? ' &rarr; ' + r.return_date : ''} &middot; ${r.nights || 7} nights</div>
          <div class="meta">&#9992;&#65039; ${r.departure_airport || 'CGN'}${r.room_type ? ' &middot; ' + r.room_type : ''}</div>
          <span class="tag ai">${r.board || 'All Inclusive'}</span>
          ${r.note ? '<span class="tag note">' + r.note + '</span>' : ''}
          <div class="price-block">
            <div class="price-total">&#8364;${(r.price_total_eur || 0).toLocaleString()}</div>
            <div class="price-pp">&#8776; &#8364;${r.price_per_person || 0}/person</div>
            ${r.booking_url ? `<a href="${r.booking_url}" target="_blank" rel="noopener" style="margin-left:auto;background:#667eea;color:white;padding:.45rem 1rem;border-radius:7px;text-decoration:none;font-size:.85rem;font-weight:600;white-space:nowrap">Book on Check24 &#8599;</a>` : ''}
          </div>
        </div>`).join('');
      document.getElementById('results').innerHTML = html;
    }
  } catch(e) {
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('results').innerHTML = '<div class="error">Error: ' + e + '</div>';
  }
  btn.disabled = false; btn.textContent = 'Search Holidays';
}

async function doCheapest() {
  const hotelName = document.getElementById('opt-hotel').value.trim();
  if (!hotelName) { alert('Enter a hotel or resort name'); return; }
  const btn = document.getElementById('cheapestBtn');
  btn.disabled = true; btn.textContent = 'Searching...';
  document.getElementById('opt-spinner').style.display = 'block';
  document.getElementById('opt-results').innerHTML = '';
  const src = document.getElementById('opt-source').value;
  document.getElementById('opt-status').textContent = 'Searching ' + src + ' for "' + hotelName + '" across date/nights combinations...';
  const childAgesRaw = document.getElementById('opt-childAges').value.trim();
  const childAges = childAgesRaw ? childAgesRaw.split(',').map(a => parseInt(a.trim())).filter(n => !isNaN(n)) : [];
  try {
    const resp = await fetch('/cheapest', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        hotel_name: hotelName,
        destination: document.getElementById('opt-dest').value,
        date_from: document.getElementById('opt-from').value,
        date_to: document.getElementById('opt-to').value,
        nights_min: parseInt(document.getElementById('opt-nights-min').value),
        nights_max: parseInt(document.getElementById('opt-nights-max').value),
        departure: document.getElementById('opt-departure').value,
        adults: parseInt(document.getElementById('opt-adults').value),
        child_ages: childAges,
        board: document.getElementById('opt-board').value,
        source: document.getElementById('opt-source').value,
      })
    });
    const data = await resp.json();
    document.getElementById('opt-spinner').style.display = 'none';
    if (data.error) {
      document.getElementById('opt-results').innerHTML = '<div class="error">' + data.error + '</div>';
    } else if (!data.results || !data.results.length) {
      document.getElementById('opt-results').innerHTML = '<div class="error">No results found for "' + hotelName + '". Check the hotel name and destination.</div>';
    } else {
      document.getElementById('opt-status').textContent = 'Found ' + data.results.length + ' price combinations — cheapest first';
      const rankBadge = i => {
        const cls = i===0?'gold':i===1?'silver':i===2?'bronze':'';
        const lbl = i===0?'1':i===1?'2':i===2?'3':(i+1);
        return `<span class="rank-badge ${cls}">${lbl}</span>`;
      };
      const rows = data.results.map((r,i) => `
        <tr class="${i===0?'winner':''}">
          <td>${rankBadge(i)}</td>
          <td><strong>${r.departure_date||'?'}</strong></td>
          <td>${r.return_date||'?'}</td>
          <td style="text-align:center">${r.nights||'?'}</td>
          <td><strong style="font-size:1.05rem">&#8364;${(r.price_total_eur||0).toLocaleString()}</strong></td>
          <td style="color:#666">&#8364;${r.price_per_person||0}/pp</td>
          <td>${r.room_type||''}</td>
          <td>${r.booking_url ? `<a href="${r.booking_url}" target="_blank" style="background:#667eea;color:white;padding:.3rem .7rem;border-radius:6px;text-decoration:none;font-size:.8rem;font-weight:600">Book &#8599;</a>` : ''}</td>
        </tr>`).join('');
      document.getElementById('opt-results').innerHTML = `
        <div class="result-card" style="margin-top:1rem;border-left-color:#10b981">
          <div class="hotel-name" style="font-size:1.2rem;margin-bottom:.8rem">&#128176; ${data.results[0].hotel||hotelName} — Price Comparison</div>
          <table class="cheapest-table">
            <thead><tr>
              <th>#</th><th>Departure</th><th>Return</th><th>Nights</th><th>Total Price</th><th>Per Person</th><th>Room</th><th></th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
          <p style="font-size:.78rem;color:#999;margin-top:.8rem">Sorted by total price. Gold = cheapest option.</p>
        </div>`;
    }
  } catch(e) {
    document.getElementById('opt-spinner').style.display = 'none';
    document.getElementById('opt-results').innerHTML = '<div class="error">Error: ' + e + '</div>';
  }
  btn.disabled = false; btn.textContent = 'Find Cheapest Prices';
}
</script>
</body>
</html>"""

async def find_cheapest_tui(hotel_name, destination, date_from, date_to,
                            nights_min, nights_max, departure, adults, child_ages, board):
    """TUI price optimizer: loads the hotel listing, finds hotel, probes each nights count."""
    n_people = adults + len(child_ages)
    board_code = BOARD_MAP.get(board, 'AI')
    tui_board = {'AI': 'AI', 'HP': 'HP', 'VP': 'VP', 'FB': 'FB'}.get(board_code, 'AI')
    child_ages_str = ','.join(str(a) for a in child_ages)
    dest_slug = EXTRA_SOURCES['TUI']['dest_map'].get(destination, destination.lower())
    dates_range = f"{date_from}-{date_to}"
    all_results = []
    seen_combos = set()

    span = nights_max - nights_min
    if span <= 0:
        nights_list = [nights_min]
    elif span <= 7:
        nights_list = list(range(nights_min, nights_max + 1))
    else:
        step = max(1, span // 7)
        nights_list = list(range(nights_min, nights_max + 1, step))
        if nights_max not in nights_list:
            nights_list.append(nights_max)

    print(f"\n=== TUI CHEAPEST: {hotel_name} | {date_from}–{date_to} | nights {nights_list} ===", flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = await browser.new_context(locale='de-DE', viewport={'width':1280,'height':900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        page = await ctx.new_page()

        hotel_href = None
        for nights in nights_list:
            tui_url = (f"https://www.tui.com/de/pauschalreisen/{dest_slug}/"
                       f"?abflughafen={departure}&reisedauer={nights}&reisezeitraum={dates_range}"
                       f"&verpflegung={tui_board}&erwachsene={adults}&kinder={len(child_ages)}&kinderalter={child_ages_str}")
            if hotel_href is None:
                print(f"  TUI listing: {tui_url}", flush=True)
                await page.goto(tui_url, wait_until='domcontentloaded', timeout=45000)
                await _accept_any_cookies(page)
                try:
                    await page.wait_for_load_state('networkidle', timeout=12000)
                except:
                    pass
                await page.wait_for_timeout(3000)
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 900)")
                    await page.wait_for_timeout(700)
                # Find hotel link
                hotel_href = await page.evaluate(f"""() => {{
                    const name = {json.dumps(hotel_name.lower())};
                    for (const a of document.querySelectorAll('a[href]')) {{
                        if (a.textContent.toLowerCase().includes(name) && a.href.includes('tui.com')) {{
                            return a.href;
                        }}
                    }}
                    return null;
                }}""")
                if hotel_href:
                    print(f"  TUI hotel link: {hotel_href[:100]}", flush=True)
                else:
                    # Qwen fallback on body text
                    body = await page.evaluate("() => document.body.innerText")
                    prompt = (f"TUI Germany website listing hotels in {destination}. "
                              f"Find the hotel URL (href) for a hotel named '{hotel_name}'. "
                              f"Return ONLY the full URL, nothing else. If not found, return NOT_FOUND.\n\nPage text:\n{body[:6000]}")
                    raw = qwen_no_think(prompt, max_tokens=200)
                    if 'NOT_FOUND' not in raw.upper() and 'http' in raw:
                        hotel_href = raw.strip().split()[0]
                    else:
                        print(f"  TUI: hotel not found on listing", flush=True)
                        await browser.close()
                        return []

            # Build detail URL with specific nights
            detail_url = hotel_href.split('?')[0] + (
                f"?abflughafen={departure}&reisedauer={nights}&reisezeitraum={dates_range}"
                f"&verpflegung={tui_board}&erwachsene={adults}&kinder={len(child_ages)}&kinderalter={child_ages_str}"
            )
            pkgs = await _scrape_tui_detail(
                page, detail_url, hotel_name, destination, adults, child_ages,
                nights, dates_range, board, n_people, tui_url
            )
            for pkg in pkgs:
                key = (pkg.get('departure_date',''), nights)
                if key not in seen_combos:
                    seen_combos.add(key)
                    all_results.append(pkg)

        await browser.close()

    all_results.sort(key=lambda x: x.get('price_total_eur', 99999))
    print(f"  TUI cheapest total: {len(all_results)}", flush=True)
    return all_results


async def find_cheapest_corendon(hotel_name, destination, date_from, date_to,
                                  nights_min, nights_max, departure, adults, child_ages, board):
    """Corendon price optimizer: loads destination listing, filters, finds hotel, probes nights."""
    n_people = adults + len(child_ages)
    board_code = BOARD_MAP.get(board, 'AI')
    child_ages_str = ','.join(str(a) for a in child_ages)
    dest_slug = EXTRA_SOURCES['Corendon']['dest_map'].get(destination, destination.lower())
    dates_range = f"{date_from}-{date_to}"
    all_results = []
    seen_combos = set()

    span = nights_max - nights_min
    nights_list = [nights_min] if span <= 0 else (
        list(range(nights_min, nights_max + 1)) if span <= 7 else
        list(range(nights_min, nights_max + 1, max(1, span // 7))) + ([nights_max] if nights_max not in range(nights_min, nights_max+1, max(1,span//7)) else [])
    )

    print(f"\n=== CORENDON CHEAPEST: {hotel_name} | {date_from}–{date_to} | nights {nights_list} ===", flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = await browser.new_context(locale='de-DE', viewport={'width':1280,'height':900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        page = await ctx.new_page()

        listing_url = f"https://www.corendon.de/{dest_slug}/"
        print(f"  Corendon listing: {listing_url}", flush=True)
        await page.goto(listing_url, wait_until='domcontentloaded', timeout=30000)
        await _accept_any_cookies(page)
        await page.wait_for_timeout(2000)
        await _click_corendon_filters(page, departure, dates_range, board)
        for _ in range(3):
            await page.evaluate("window.scrollBy(0,900)")
            await page.wait_for_timeout(700)

        # Find hotel card link
        hotel_href = await page.evaluate(f"""() => {{
            const name = {json.dumps(hotel_name.lower())};
            for (const a of document.querySelectorAll('a[href]')) {{
                if (a.textContent.toLowerCase().includes(name) && a.href.includes('corendon')) {{
                    return a.href;
                }}
            }}
            return null;
        }}""")

        if not hotel_href:
            body = await page.evaluate("() => document.body.innerText")
            if hotel_name.lower() not in body.lower():
                print(f"  Corendon: '{hotel_name}' not found", flush=True)
                await browser.close()
                return []
            hotel_href = listing_url  # use listing as fallback

        print(f"  Corendon hotel href: {hotel_href[:100]}", flush=True)

        # Corendon hotel detail pages have prices per date in their calendar
        # Load the hotel detail page for each nights value
        for nights in nights_list:
            try:
                await page.goto(hotel_href, wait_until='domcontentloaded', timeout=30000)
                await _accept_any_cookies(page)
                await _click_corendon_filters(page, departure, dates_range, board)
                await page.wait_for_timeout(3000)
                text = await page.evaluate("() => document.body.innerText")
                prompt = (
                    f"Corendon hotel page for '{hotel_name}' in {destination}.\n"
                    f"Extract all available package offers for {nights} nights, departing from {departure} "
                    f"between {date_from} and {date_to}.\n"
                    f"Return ONLY a JSON array:\n"
                    f'[{{"hotel":"{hotel_name}","resort":"","destination":"{destination}",'
                    f'"departure_date":"DD.MM.YYYY","return_date":"DD.MM.YYYY","nights":{nights},'
                    f'"price_total_eur":0,"price_per_person":0,"board":"{board}","room_type":"","departure_airport":"{departure}"}}]\n'
                    f"Only include rows with a real price > 0.\n\nPage text:\n{text[:8000]}"
                )
                raw = qwen_no_think(prompt, max_tokens=1500)
                m = re.search(r'\[.*\]', raw, re.DOTALL)
                if m:
                    for pkg in json.loads(m.group()):
                        if isinstance(pkg, dict) and pkg.get('price_total_eur', 0) > 0:
                            key = (pkg.get('departure_date',''), nights)
                            if key not in seen_combos:
                                seen_combos.add(key)
                                pkg['source'] = 'Corendon'
                                pkg['booking_url'] = hotel_href
                                pkg['nights'] = nights
                                pkg['price_per_person'] = round(pkg['price_total_eur'] / max(1, n_people))
                                all_results.append(pkg)
                print(f"  Corendon {nights}n: {len([r for r in all_results if r['nights']==nights])} offers", flush=True)
            except Exception as e:
                print(f"  Corendon {nights}n error: {e}", flush=True)

        await browser.close()

    all_results.sort(key=lambda x: x.get('price_total_eur', 99999))
    return all_results


async def find_cheapest_deals(hotel_name, destination, date_from, date_to,
                              nights_min, nights_max, departure, adults, child_ages, board, source='Check24'):
    """For a named hotel, try all nights-duration × departure-date combos and return cheapest."""
    if source == 'TUI':
        return await find_cheapest_tui(hotel_name, destination, date_from, date_to,
                                       nights_min, nights_max, departure, adults, child_ages, board)
    if source == 'Corendon':
        return await find_cheapest_corendon(hotel_name, destination, date_from, date_to,
                                            nights_min, nights_max, departure, adults, child_ages, board)
    n_people = adults + len(child_ages)
    board_code = BOARD_MAP.get(board, 'AI')
    child_ages_str = ','.join(str(a) for a in child_ages)
    dest_slug = DEST_MAP.get(destination, destination.lower())

    # Determine which night counts to try (cap at 8 probes to avoid huge runtimes)
    span = nights_max - nights_min
    if span <= 0:
        nights_list = [nights_min]
    elif span <= 7:
        nights_list = list(range(nights_min, nights_max + 1))
    else:
        step = max(1, span // 7)
        nights_list = list(range(nights_min, nights_max + 1, step))
        if nights_max not in nights_list:
            nights_list.append(nights_max)

    # Parse month range for Sparkalender clicks
    def de_to_month_label(d):  # "01.10.2026" → "Oktober 2026"
        parts = d.split('.')
        return f"{MONTH_DE.get(parts[1], '')} {parts[2]}" if len(parts) == 3 else ''

    months_to_click = []
    # collect unique month labels between date_from and date_to
    from datetime import date, timedelta
    try:
        d_from = date(int(date_from[6:]), int(date_from[3:5]), int(date_from[:2]))
        d_to   = date(int(date_to[6:]),   int(date_to[3:5]),   int(date_to[:2]))
        cur = d_from.replace(day=1)
        while cur <= d_to:
            label = f"{MONTH_DE.get(f'{cur.month:02d}', '')} {cur.year}"
            if label not in months_to_click:
                months_to_click.append(label)
            # advance one month
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
    except:
        months_to_click = [de_to_month_label(date_from)]

    all_results = []
    print(f"\n=== CHEAPEST SEARCH: {hotel_name} | {date_from}–{date_to} | {nights_min}–{nights_max} nights ===", flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled'
        ])
        ctx = await browser.new_context(
            viewport={'width': 1280, 'height': 900}, locale='de-DE',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            extra_http_headers={'Accept-Language': 'de-DE,de;q=0.9'}
        )
        await ctx.add_cookies([C24_CONSENT_COOKIE])
        page = await ctx.new_page()
        await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

        dates_range = f"{date_from}-{date_to}"

        # Convert DE date format (DD.MM.YYYY) to ISO (YYYY-MM-DD) for URL params
        def de_to_iso(d):
            p = d.split('.')
            return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else d

        iso_from = de_to_iso(date_from)
        iso_to   = de_to_iso(date_to)

        # --- Find hotel ID via Check24 autocomplete (works for all destinations incl. Turkey) ---
        dest_page_url = f"https://urlaub.check24.de/pauschalreisen/{dest_slug}"
        print(f"  Loading dest page: {dest_page_url}", flush=True)
        await page.goto(dest_page_url, wait_until='domcontentloaded', timeout=45000)
        await accept_cookies(page)
        await page.wait_for_timeout(2000)

        # Type hotel name into autocomplete input
        search_term = hotel_name[:20]
        await page.click('#c24-travel-destination-element')
        await page.wait_for_timeout(300)
        await page.type('#c24-travel-destination-element', search_term, delay=80)
        await page.wait_for_timeout(3500)

        # Playwright native click on matching LI (JS .click() doesn't fire jQuery UI select)
        li_items = await page.query_selector_all('li.c24-travel-hotelfilter-item')
        print(f"  Autocomplete LIs: {len(li_items)}", flush=True)
        # Destination keywords to prefer country-correct match
        dest_kw_map = {
            'turkey': ['türkei', 'turkey', 'antalya', 'alanya', 'belek', 'marmaris', 'bodrum', 'kemer', 'side', 'lara'],
            'greece': ['griechenland', 'greece', 'kreta', 'rhodos', 'korfu', 'kos'],
            'spain': ['spanien', 'spain', 'mallorca', 'tenerife', 'gran canaria', 'ibiza'],
            'egypt': ['ägypten', 'egypt', 'hurghada', 'sharm'],
            'portugal': ['portugal', 'algarve', 'madeira'],
            'albania': ['albanien', 'albania', 'durres'],
        }
        dest_lower = destination.lower()
        dest_kws = next((v for k, v in dest_kw_map.items() if k in dest_lower), [])
        matched_li = None
        search_lower = hotel_name.lower()[:12]
        # Pass 1: match hotel name AND destination country
        for li in li_items:
            txt = (await li.text_content() or '').lower()
            if search_lower in txt and (not dest_kws or any(kw in txt for kw in dest_kws)):
                matched_li = li
                print(f"  Matched LI: {(await li.text_content() or '').strip()[:80]}", flush=True)
                break
        # Pass 2: hotel name only (no country filter)
        if not matched_li:
            for li in li_items:
                txt = (await li.text_content() or '').lower()
                if search_lower in txt:
                    matched_li = li
                    print(f"  Matched LI (no country): {(await li.text_content() or '').strip()[:80]}", flush=True)
                    break
        if not matched_li and li_items:
            matched_li = li_items[0]
            print(f"  Fallback LI: {(await li_items[0].text_content() or '').strip()[:80]}", flush=True)

        hotel_id = None
        resolved_name = hotel_name
        if matched_li:
            await matched_li.click()
            await page.wait_for_timeout(1500)
            hotel_id = await page.evaluate("() => (document.getElementById('c24-travel-hotel-id')||{}).value || ''")
            dest_label = await page.evaluate("() => (document.getElementById('c24-travel-destination-label')||{}).value || ''")
            if dest_label:
                resolved_name = dest_label.strip()
            print(f"  Hotel ID: {hotel_id} | Label: {dest_label}", flush=True)

        if not hotel_id:
            print(f"  Could not get hotel ID for '{hotel_name}' — aborting", flush=True)
            await browser.close()
            return []

        # ONE page load — price-calendar API returns all dates × durations in one shot
        from datetime import date as _date, timedelta
        d_from = _date(int(date_from[6:]), int(date_from[3:5]), int(date_from[:2]))
        d_to   = _date(int(date_to[6:]),   int(date_to[3:5]),   int(date_to[:2]))

        def iso_to_de(s):  # "2026-10-01" → "01.10.2026"
            return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if s and len(s) == 10 else s

        detail_url = (
            f"https://urlaub.check24.de/suche/angebot"
            f"?airport={departure}&hotelId={hotel_id}&verpflegung={board_code}"
            f"&erwachsene={adults}&kinder={len(child_ages)}&kinderalter={child_ages_str}"
            f"&reisedauer={nights_min}&ab={departure}"
            f"&reisezeitraum={dates_range}&departureDate={iso_from}&returnDate={iso_to}"
        )
        print(f"  Loading offers page (one shot): {detail_url[:100]}", flush=True)
        try:
            api_responses = []

            async def capture_response(resp):
                if resp.status == 200 and 'check24' in resp.url:
                    ct = resp.headers.get('content-type', '')
                    if 'json' in ct:
                        try:
                            body = await resp.text()
                            if '"price"' in body or '"offerData"' in body:
                                api_responses.append({'url': resp.url, 'body': body})
                        except:
                            pass

            page.on('response', capture_response)
            await page.goto(detail_url, wait_until='domcontentloaded', timeout=30000)
            await dismiss_cookies(page)
            try:
                await page.wait_for_load_state('networkidle', timeout=12000)
            except:
                pass
            await page.wait_for_timeout(2000)
            page.remove_listener('response', capture_response)

            print(f"  API responses captured: {len(api_responses)}", flush=True)

            seen_combos = set()
            found_total = 0

            for ar in api_responses:
                try:
                    d = json.loads(ar['body'])
                except:
                    continue
                url_path = ar['url'].split('?')[0]
                if 'price-calendar' not in url_path:
                    continue
                if found_total > 0:
                    continue  # already parsed a price-calendar, skip duplicates

                # offerData: ISO dates, price=total for searched party, travelDuration=nights
                entries = d.get('offerData', [])
                print(f"  price-calendar: {len(entries)} entries, offerCount={d.get('offerCount',0)}", flush=True)
                for e in entries:
                    dep_iso = e.get('departureDate', '')
                    ret_iso = e.get('returnDate', '')
                    price   = float(e.get('price', 0))
                    dur     = int(e.get('travelDuration', 0))

                    if not dep_iso or price <= 0:
                        continue
                    # Accept all durations — calendar shows cheapest per date

                    # Convert ISO → DE format
                    dep = iso_to_de(dep_iso)
                    ret = iso_to_de(ret_iso) if ret_iso else ''

                    # Validate departure in requested range
                    try:
                        dp = [int(x) for x in dep_iso.split('-')]
                        dep_dt = _date(dp[0], dp[1], dp[2])
                        if not (d_from <= dep_dt <= d_to):
                            skip_date += 1
                            continue
                    except:
                        continue
                    if not ret:
                        ret = (dep_dt + timedelta(days=dur)).strftime('%d.%m.%Y')

                    combo_key = (dep, dur)
                    if combo_key in seen_combos:
                        continue
                    seen_combos.add(combo_key)

                    # Build a deep-link URL for this specific departure + duration
                    dep_url = (
                        f"https://urlaub.check24.de/suche/angebot"
                        f"?airport={departure}&hotelId={hotel_id}&verpflegung={board_code}"
                        f"&erwachsene={adults}&kinder={len(child_ages)}&kinderalter={child_ages_str}"
                        f"&reisedauer={dur}&ab={departure}"
                        f"&reisezeitraum={dates_range}&departureDate={dep_iso}&returnDate={iso_to}"
                    )
                    all_results.append({
                        'hotel': resolved_name, 'destination': destination,
                        'departure_date': dep, 'return_date': ret, 'nights': dur,
                        'price_total_eur': round(price, 2),
                        'price_per_person': round(price / max(1, n_people)),
                        'board': 'All Inclusive', 'departure_airport': departure,
                        'source': 'Check24', 'booking_url': dep_url,
                    })
                    found_total += 1

            print(f"  Total from API: {found_total} offers", flush=True)

            # Fallback: DOM extraction if API gave nothing
            if found_total == 0:
                nights = nights_min
                dom_offers = await page.evaluate(f"""() => {{
                    const offers = []; const seen = new Set();
                    for (const el of document.querySelectorAll('tr,li,[class*="offer"],[class*="row"],[class*="item"]')) {{
                        if (el.children.length > 15) continue;
                        const text = el.textContent.replace(/\\s+/g,' ').trim();
                        const dateM = text.match(/\\b(\\d{{2}}\\.\\d{{2}}\\.\\d{{4}})\\b/g);
                        const priceM = text.match(/[€][\\s]*(\\d[\\d.,]*)|(\\d[\\d.,]*)[\\s]*€/g);
                        if (dateM && priceM && !seen.has(dateM[0])) {{
                            seen.add(dateM[0]);
                            offers.push({{dep:dateM[0],ret:dateM[1]||'',raw_price:priceM[0]||'',text:text.slice(0,250)}});
                            if (offers.length >= 40) break;
                        }}
                    }}
                    return offers;
                }}""")
                for off in dom_offers:
                    dep = off['dep']
                    try:
                        dp = [int(x) for x in dep.split('.')]
                        dep_dt = _date(dp[2], dp[1], dp[0])
                        if not (d_from <= dep_dt <= d_to): continue
                    except:
                        continue
                    raw = re.sub(r'[€\s]', '', off['raw_price']).replace('.','').replace(',','.')
                    try:
                        price = float(raw)
                        if not (100 < price < 50000): continue
                    except:
                        continue
                    ret = off['ret'] or (dep_dt + timedelta(days=nights)).strftime('%d.%m.%Y')
                    combo_key = (dep, nights)
                    if combo_key in seen_combos: continue
                    seen_combos.add(combo_key)
                    all_results.append({
                        'hotel': resolved_name, 'destination': destination,
                        'departure_date': dep, 'return_date': ret, 'nights': nights,
                        'price_total_eur': round(price, 2),
                        'price_per_person': round(price / max(1, n_people)),
                        'board': 'All Inclusive', 'departure_airport': departure,
                        'source': 'Check24', 'booking_url': detail_url,
                    })
                    found_total += 1
                print(f"  DOM fallback: {found_total} offers", flush=True)

        except Exception as e:
            print(f"  Offer fetch error: {e}", flush=True)


        await browser.close()

    all_results.sort(key=lambda x: x.get('price_total_eur', 99999))
    print(f"  Total cheapest results: {len(all_results)}", flush=True)
    return all_results


@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    try:
        results = asyncio.run(run_search(
            destinations=data.get('destinations', ['Greece', 'Turkey', 'Egypt']),
            departure=data.get('departure', 'CGN'),
            dates=data.get('dates', '01.10.2026-31.10.2026'),
            adults=data.get('adults', 2),
            children=data.get('children', 2),
            child_ages=data.get('child_ages', [5, 0]),
            nights=data.get('nights', 7),
            board=data.get('board', 'All Inclusive'),
            luxury=data.get('luxury', ''),
            waterpark=data.get('waterpark', False),
            sources=data.get('sources', ['Check24'])
        ))
        return jsonify({"results": results})
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()})

@app.route('/cheapest', methods=['POST'])
def cheapest():
    data = request.json
    try:
        results = asyncio.run(find_cheapest_deals(
            hotel_name=data.get('hotel_name', ''),
            destination=data.get('destination', 'Greece'),
            date_from=data.get('date_from', '01.10.2026'),
            date_to=data.get('date_to', '31.10.2026'),
            nights_min=int(data.get('nights_min', 7)),
            nights_max=int(data.get('nights_max', 14)),
            departure=data.get('departure', 'CGN'),
            adults=int(data.get('adults', 2)),
            child_ages=data.get('child_ages', [5, 0]),
            board=data.get('board', 'All Inclusive'),
            source=data.get('source', 'Check24'),
        ))
        return jsonify({"results": results})
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()})


if __name__ == '__main__':
    print("Starting Holiday Finder GUI on port 5001...", flush=True)
    app.run(host='0.0.0.0', port=5001, debug=False)
