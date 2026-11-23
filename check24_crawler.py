#!/usr/bin/env python3
"""
Check24 Live Price Crawler — Meivakantie 2027
Intercepteert de /suche/json/dynamic/offer API calls die Check24 maakt
bij het laden van de pagina. Geen knoppen klikken nodig.

Gebruik:
    pip install playwright
    playwright install chromium
    python check24_crawler.py

Optioneel: stuur Windows-melding bij goede prijs
    pip install winotify
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import os
import sys

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Playwright niet geinstalleerd. Run: pip install playwright && playwright install chromium")
    raise

# GitHub Actions modus detecteren
IS_GH_ACTIONS = bool(os.environ.get("GITHUB_ACTIONS"))

# ── Configuratie ────────────────────────────────────────────────────────────
HOTELS = [
    {"name": "BAYOU Lara by Barut",  "hotelId": 15718, "areaId": 578, "alert_below": 3700},
    {"name": "Delphin Imperial",      "hotelId": 28054, "areaId": 578, "alert_below": 3900},
    {"name": "Delphin BE Grand",      "hotelId": 12975, "areaId": 578, "alert_below": 3900},
]

AIRPORTS     = ["DTM", "CGN"]          # Dortmund + Köln
DEPARTURE    = "2027-04-24"
RETURN_DATE  = "2027-05-05"
DAYS         = 12                      # = 11 nachten (Check24: reisdagen incl. heen+terug)
ROOM         = "A-A-5-0"              # 2 volw. + kind 5jr + baby gratis
CATERING     = "allinclusive"

OUTPUT_DIR   = Path(__file__).parent   # sla JSON op naast dit script
HEADLESS     = True                    # False = je ziet de browser openen

# ── Prijsalert ────────────────────────────────────────────────────────────────
def send_notification(title: str, message: str):
    if IS_GH_ACTIONS:
        return  # GitHub gebruikt create_github_issue

    # Windows toast (lokaal)
    try:
        from winotify import Notification
        toast = Notification(app_id="Check24 Crawler", title=title, msg=message, duration="long")
        toast.show()
    except ImportError:
        pass


def create_github_issue(title: str, body: str):
    """Maakt een GitHub Issue aan — geeft automatisch een email naar de repo-eigenaar."""
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")  # bijv. "kofori00/holidays"
    if not token or not repo:
        return

    try:
        import urllib.request, json as _json
        payload = _json.dumps({
            "title":  title,
            "body":   body,
            "labels": ["price-alert"],
        }).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept":        "application/vnd.github+json",
                "Content-Type":  "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"  📬 GitHub Issue aangemaakt: {title}")
    except Exception as e:
        print(f"  ⚠ Issue aanmaken mislukt: {e}")

# ── Check24 URL bouwen ───────────────────────────────────────────────────────
def build_url(hotel: dict, airport: str) -> str:
    return (
        f"https://urlaub.check24.de/suche/angebot"
        f"?airport={airport}"
        f"&transportType=flight"
        f"&roomAllocation={ROOM}"
        f"&departureDate={DEPARTURE}"
        f"&returnDate={RETURN_DATE}"
        f"&days={DAYS}"
        f"&hotelId={hotel['hotelId']}"
        f"&areaId={hotel['areaId']}"
        f"&catering={CATERING}"
        f"&offerSort=price"
    )

# ── Eén hotel + luchthaven scrapen ───────────────────────────────────────────
async def scrape_one(context, hotel: dict, airport: str) -> dict:
    url      = build_url(hotel, airport)
    captured = []

    page = await context.new_page()

    # Onderschep ALLE responses van de dynamic/offer API
    async def on_response(response):
        if "dynamic/offer" in response.url and response.status == 200:
            try:
                body = await response.json()
                if body:
                    captured.append(body)
            except Exception:
                pass

    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Wacht tot de Vakanzprüfung klaar is (~20 sec bij meivakantie)
        await asyncio.sleep(20)
    except Exception as e:
        print(f"  ✗ Timeout/error voor {hotel['name']} / {airport}: {e}")
        await page.close()
        return {"hotel": hotel["name"], "airport": airport, "error": str(e)}
    finally:
        await page.close()

    # Volg pollUrl om alle batches te krijgen (Check24 laadt offers in meerdere rondes)
    poll_urls_seen = set()
    for body in list(captured):
        poll_url = body.get("pollUrl") if isinstance(body, dict) else None
        if poll_url and poll_url not in poll_urls_seen:
            poll_urls_seen.add(poll_url)
            try:
                # Open nieuwe page om pollUrl op te vragen
                poll_page = await context.new_page()
                async def on_poll_resp(r, _captured=captured):
                    if "dynamic/offer" in r.url and r.status == 200:
                        try:
                            b = await r.json()
                            if b:
                                _captured.append(b)
                        except Exception:
                            pass
                poll_page.on("response", on_poll_resp)
                await poll_page.goto(
                    f"https://urlaub.check24.de{poll_url}" if poll_url.startswith("/") else poll_url,
                    wait_until="domcontentloaded", timeout=15_000
                )
                await asyncio.sleep(8)
                await poll_page.close()
            except Exception:
                pass

    # Verwerk de gevangen API-responses
    # Structuur: { status, items: { id: offer }, tourOperatorList, pollUrl, ... }
    all_offers = []
    op_names   = {}  # operatorCode -> name

    for body in captured:
        if not isinstance(body, dict):
            continue

        # Operator-namen bijhouden
        for op in body.get("tourOperatorList", []):
            if isinstance(op, dict) and "code" in op:
                op_names[op["code"]] = op.get("name", op["code"])

        # Offers ophalen
        items = body.get("items", {})
        if not isinstance(items, dict):
            continue

        for offer_id, offer in items.items():
            if not isinstance(offer, dict):
                continue

            # Prijs ophalen
            price_obj = offer.get("price", {})
            price = price_obj.get("total") or price_obj.get("effective")
            if price is None:
                continue
            try:
                price = float(price)
            except (ValueError, TypeError):
                continue

            # Operator
            op_code  = offer.get("tourOperatorCode", "?")
            operator = op_names.get(op_code, op_code)

            # Kamer & maaltijd
            accom = offer.get("accommodationData", {})
            room_desc = accom.get("roomDescription", {})
            room  = f"{room_desc.get('name','')} {room_desc.get('description','')}".strip()
            meal  = accom.get("mealType", "?")

            # Vluchtinfo
            flight  = offer.get("flight", {})
            out_f   = flight.get("outbound", {})
            ret_f   = flight.get("inbound",  {})

            out_dep = (out_f.get("departure") or {}).get("dateTime", "?")
            out_arr = (out_f.get("arrival")   or {}).get("dateTime", "?")
            ret_dep = (ret_f.get("departure") or {}).get("dateTime", "?")
            ret_arr = (ret_f.get("arrival")   or {}).get("dateTime", "?")

            # Vluchtnummer
            out_segs = out_f.get("segments", [])
            out_num  = out_segs[0].get("flightNumber", "?") if out_segs else "?"
            ret_segs = ret_f.get("segments", [])
            ret_num  = ret_segs[0].get("flightNumber", "?") if ret_segs else "?"

            # Transfer & annulering
            travel = offer.get("travelAttributes", {})

            all_offers.append({
                "totalPrice":  price,
                "operator":    operator,
                "operatorCode": op_code,
                "room":        room or "?",
                "catering":    meal,
                "outDep":      out_dep[:16] if len(out_dep) > 10 else out_dep,
                "outArr":      out_arr[:16] if len(out_arr) > 10 else out_arr,
                "outFlight":   out_num,
                "retDep":      ret_dep[:16] if len(ret_dep) > 10 else ret_dep,
                "retArr":      ret_arr[:16] if len(ret_arr) > 10 else ret_arr,
                "retFlight":   ret_num,
                "nights":      travel.get("overnightStays", 11),
            })

    if not all_offers:
        # Debug: sla ruwe responses op om formaat te inspecteren
        debug_path = OUTPUT_DIR / f"debug_{hotel['hotelId']}_{airport}.json"
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(captured[:2], f, ensure_ascii=False, indent=2)
        return {
            "hotel":   hotel["name"],
            "airport": airport,
            "url":     url,
            "scraped": datetime.now().isoformat(timespec="seconds"),
            "offers":  [],
            "note":    f"Geen offers onderschept ({len(captured)} API-calls gevangen) — debug: {debug_path.name}",
        }

    # Sorteren op prijs
    all_offers.sort(key=lambda x: x["totalPrice"])
    cheapest = all_offers[0]

    return {
        "hotel":        hotel["name"],
        "airport":      airport,
        "url":          url,
        "scraped":      datetime.now().isoformat(timespec="seconds"),
        "cheapest":     cheapest,
        "top5":         all_offers[:5],
        "total_found":  len(all_offers),
    }

# ── Alle hotels + luchthavens scrapen ────────────────────────────────────────
async def run_all():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    results   = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Gebruik een context met echte user-agent + cookies zodat Check24 alle aanbiedingen laadt
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="de-DE",
            timezone_id="Europe/Berlin",
        )
        # c24consent=fam zorgt ervoor dat Check24 de volledige aanbiedings-API aanroept
        await context.add_cookies([
            {"name": "c24consent", "value": "fam",
             "domain": "urlaub.check24.de", "path": "/"},
            {"name": "c24consent", "value": "fam",
             "domain": ".check24.de", "path": "/"},
        ])

        for hotel in HOTELS:
            for airport in AIRPORTS:
                print(f"Scraping: {hotel['name']} / {airport} ...", flush=True)
                result = await scrape_one(context, hotel, airport)
                results.append(result)

                # Toon resultaat direct
                if "cheapest" in result:
                    c = result["cheapest"]
                    print(f"  ✓ Goedkoopste: €{c['totalPrice']:,.0f}  |  {c['operator']}  |  {c['room']}")
                    print(f"    Heen:  {c['outDep']} ({c['outFlight']}) → {c['outArr']}")
                    print(f"    Terug: {c['retDep']} ({c['retFlight']}) → {c['retArr']}")

                    # Prijsalert
                    if c["totalPrice"] < hotel["alert_below"]:
                        alert_msg = (
                            f"{hotel['name']} / {airport}: "
                            f"€{c['totalPrice']:,.0f} ({c['operator']})\n"
                            f"Heen:  {c['outDep']} ({c['outFlight']}) → {c['outArr']}\n"
                            f"Terug: {c['retDep']} ({c['retFlight']}) → {c['retArr']}\n\n"
                            f"[Boek hier]({result['url']})"
                        )
                        send_notification("🏖 Goede vakantieprijs!", alert_msg)
                        print(f"  🔔 ALERT: prijs onder €{hotel['alert_below']}!")
                        if IS_GH_ACTIONS:
                            create_github_issue(
                                title=f"💰 Prijsalert: {hotel['name']} / {airport} = €{c['totalPrice']:,.0f}",
                                body=alert_msg,
                            )
                elif "error" not in result:
                    print(f"  ✗ Geen offers — {result.get('note','')}")

                # Kleine pauze tussen requests (voorkom throttling)
                await asyncio.sleep(2)

        await context.close()
        await browser.close()

    # Opslaan als JSON
    out_path = OUTPUT_DIR / f"check24_live_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nOpgeslagen: {out_path}")

    # Overzichtstabel printen
    print_summary(results)

    # GitHub Actions Job Summary (zichtbaar in de Actions UI)
    if IS_GH_ACTIONS:
        write_github_summary(results, timestamp)

    return results


def write_github_summary(results: list, timestamp: str):
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    lines = [
        f"## Check24 Prijsoverzicht — {timestamp.replace('_', ' ')}",
        "",
        "| Hotel | Vliegveld | Prijs | Operator | Kamer | Heen | Terug |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        hotel   = r.get("hotel", "?")
        airport = r.get("airport", "?")
        if "cheapest" in r:
            c     = r["cheapest"]
            price = f"**€{c['totalPrice']:,.0f}**" if c["totalPrice"] < 3700 else f"€{c['totalPrice']:,.0f}"
            lines.append(
                f"| {hotel} | {airport} | {price} | {c['operator']} | {c['room'][:30]} "
                f"| {c['outDep'][11:16]} ({c['outFlight']}) | {c['retDep'][11:16]} ({c['retFlight']}) |"
            )
        else:
            lines.append(f"| {hotel} | {airport} | geen | — | — | — | — |")
    lines += ["", f"*Scrape tijd: {timestamp}*"]
    with open(summary_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

# ── Overzichtstabel ───────────────────────────────────────────────────────────
def print_summary(results: list):
    print("\n" + "=" * 72)
    print(f"{'Hotel':<28} {'Vliegveld':<8} {'Prijs':>8}  {'Operator':<22}")
    print("=" * 72)
    for r in results:
        hotel   = r.get("hotel", "?")[:27]
        airport = r.get("airport", "?")
        if "cheapest" in r:
            price = f"€{r['cheapest']['totalPrice']:,.0f}"
            op    = r["cheapest"]["operator"][:21]
        elif "error" in r:
            price = "ERROR"
            op    = r["error"][:21]
        else:
            price = "geen"
            op    = r.get("note", "")[:21]
        print(f"{hotel:<28} {airport:<8} {price:>8}  {op:<22}")
    print("=" * 72)

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(run_all())
