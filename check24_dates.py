#!/usr/bin/env python3
"""
Check24 Datumscanner — Meivakantie 2027
Gebruikt de prijskalender-API om alle goedkope vertrekdata te vinden.
Geen Playwright nodig — snelle HTTP-requests.

Gebruik:
    pip install requests beautifulsoup4
    python check24_dates.py
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

IS_GH_ACTIONS = bool(os.environ.get("GITHUB_ACTIONS"))

HOTELS = [
    {"name": "BAYOU Lara by Barut",  "hotelId": 15718, "areaId": 578, "alert_below": 3700},
    {"name": "Delphin Imperial",      "hotelId": 28054, "areaId": 578, "alert_below": 3900},
    {"name": "Delphin BE Grand",      "hotelId": 12975, "areaId": 578, "alert_below": 3900},
]

AIRPORTS  = ["DTM", "CGN"]
WIN_START = "2027-04-24"   # begin zoekvenster (eerste vakantiedag)
WIN_END   = "2027-05-08"   # einde zoekvenster
NIGHTS    = [10, 11, 12]   # te testen nachten
ROOM      = "A-A-5-0"
CATERING  = "allinclusive"
OUTPUT_DIR = Path(__file__).parent

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,nl;q=0.8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def build_search_url(hotel: dict, airport: str, nights: int) -> str:
    return (
        f"https://urlaub.check24.de/suche/angebot"
        f"?airport={airport}"
        f"&transportType=flight"
        f"&roomAllocation={ROOM}"
        f"&departureDate={WIN_START}"
        f"&returnDate={WIN_END}"
        f"&days={nights}"
        f"&pageArea=package"
        f"&areaId={hotel['areaId']}"
        f"&hotelId={hotel['hotelId']}"
        f"&offerSort=price"
        f"&verpflegung={CATERING}"
    )


def get_client_id(session: requests.Session, search_url: str) -> str:
    """Haal clientId op uit de Check24 HTML-pagina."""
    try:
        r = session.get(search_url, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(r'"clientId"\s*:\s*"([^"]+)"', text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def fetch_calendar(session: requests.Session, hotel: dict, airport: str, nights: int) -> list:
    """Vraag de prijskalender op voor dit hotel/luchthaven/nachten."""
    search_url = build_search_url(hotel, airport, nights)
    client_id  = get_client_id(session, search_url)

    post_data = {
        "searchUrl":     search_url,
        "completeResult": "1",
        "clientId":      client_id,
        "initialCall":   "1",
    }

    try:
        r = session.post(
            "https://urlaub.check24.de/suche/json/offer/price-calendar",
            data=post_data,
            headers={"Referer": search_url},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  ✗ API {r.status_code} voor {hotel['name']} / {airport} / {nights}N")
            return []
        data = r.json()
    except Exception as e:
        print(f"  ✗ Fout: {e}")
        return []

    offers = []
    for item in data.get("offerData", []):
        dep   = item.get("departureDate", "")
        ret   = item.get("returnDate", "")
        price = item.get("price", 0)
        dur   = int(item.get("travelDays", item.get("travelDuration", nights)))

        if not dep or not price or price <= 0:
            continue
        if not (WIN_START <= dep <= WIN_END):
            continue

        try:
            price = float(price)
        except (ValueError, TypeError):
            continue

        offers.append({
            "hotel":       hotel["name"],
            "airport":     airport,
            "nights":      dur,
            "departure":   dep,
            "return":      ret,
            "totalPrice":  price,
            "pricePerPax": round(price / 4, 2),
            "url": (
                f"https://urlaub.check24.de/suche/angebot"
                f"?airport={airport}&transportType=flight"
                f"&roomAllocation={ROOM}"
                f"&departureDate={dep}&returnDate={ret}&days={dur}"
                f"&areaId={hotel['areaId']}&hotelId={hotel['hotelId']}"
                f"&catering={CATERING}&offerSort=price"
            ),
        })

    return offers


def create_github_issue(title: str, body: str):
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return
    try:
        import urllib.request, json as _json
        payload = _json.dumps({
            "title":  title,
            "body":   body,
            "labels": ["price-alert", "date-scan"],
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
        print(f"  📬 GitHub Issue: {title}")
    except Exception as e:
        print(f"  ⚠ Issue mislukt: {e}")


def previous_best_price():
    """Laagste prijs uit eerdere datumscanner-Issues (open én gesloten), of None."""
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    prices = []
    try:
        for page in range(1, 11):
            r = requests.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={"labels": "date-scan", "state": "all", "per_page": 100, "page": page},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=10,
            )
            r.raise_for_status()
            batch = r.json()
            for issue in batch:
                m = re.search(r"€([\d,]+)", issue["title"])
                if m:
                    prices.append(int(m.group(1).replace(",", "")))
            if len(batch) < 100:
                break
    except Exception as e:
        print(f"  ⚠ Eerdere Issues ophalen mislukt: {e}")
        return None
    return min(prices) if prices else None


def write_github_summary(all_offers: list, timestamp: str):
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    lines = [
        f"## Datumscanner — {timestamp.replace('_', ' ')}",
        f"Zoekvenster: {WIN_START} → {WIN_END} | Nachten: {', '.join(map(str, NIGHTS))} | Luchthavens: {', '.join(AIRPORTS)}",
        "",
        "### Top 20 goedkoopste aanbiedingen",
        "",
        "| Prijs | Hotel | Vliegveld | Vertrek | Terug | Nachten |",
        "|---|---|---|---|---|---|",
    ]

    top20 = sorted(all_offers, key=lambda x: x["totalPrice"])[:20]
    for o in top20:
        flag = "🔥" if o["totalPrice"] < 3700 else ("✅" if o["totalPrice"] < 3900 else "")
        lines.append(
            f"| {flag} **€{o['totalPrice']:,.0f}** | {o['hotel']} | {o['airport']} "
            f"| {o['departure']} | {o['return']} | {o['nights']}N |"
        )

    # Per hotel de goedkoopste datum
    lines += ["", "### Goedkoopste datum per hotel + luchthaven", ""]
    lines += ["| Hotel | Vliegveld | Beste datum | Prijs | Nachten |", "|---|---|---|---|---|"]

    seen = set()
    for o in sorted(all_offers, key=lambda x: x["totalPrice"]):
        key = (o["hotel"], o["airport"])
        if key not in seen:
            seen.add(key)
            flag = "🔥" if o["totalPrice"] < 3700 else ("✅" if o["totalPrice"] < 3900 else "")
            lines.append(
                f"| {o['hotel']} | {o['airport']} | {o['departure']} → {o['return']} "
                f"| {flag} **€{o['totalPrice']:,.0f}** | {o['nights']}N |"
            )

    lines += ["", f"*Scan tijd: {timestamp} | {len(all_offers)} aanbiedingen gevonden*"]

    with open(summary_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M")
    session    = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set("c24consent", "fam", domain=".check24.de")

    all_offers: list = []
    alert_offers: list = []

    print(f"Datumscanner — {WIN_START} t/m {WIN_END}")
    print(f"Hotels: {len(HOTELS)} | Luchthavens: {AIRPORTS} | Nachten: {NIGHTS}")
    print("=" * 72)

    for hotel in HOTELS:
        for airport in AIRPORTS:
            hotel_offers: list = []
            for nights in NIGHTS:
                print(f"  {hotel['name']} / {airport} / {nights}N ...", end=" ", flush=True)
                offers = fetch_calendar(session, hotel, airport, nights)
                print(f"{len(offers)} data")
                hotel_offers.extend(offers)
                time.sleep(0.3)   # voorkom throttling

            hotel_offers.sort(key=lambda x: x["totalPrice"])
            all_offers.extend(hotel_offers)

            if hotel_offers:
                best = hotel_offers[0]
                print(f"  → Beste: €{best['totalPrice']:,.0f} op {best['departure']} ({best['nights']}N)")

                if best["totalPrice"] < hotel["alert_below"]:
                    alert_offers.append(best)
                    print(f"     🔔 ALERT! Onder €{hotel['alert_below']}")

    # Overzicht
    print("\n" + "=" * 72)
    print(f"{'Hotel':<28} {'AP':<5} {'Beste datum':<13} {'Prijs':>8}  {'Nachten'}")
    print("=" * 72)
    seen = set()
    for o in sorted(all_offers, key=lambda x: x["totalPrice"]):
        key = (o["hotel"], o["airport"])
        if key not in seen:
            seen.add(key)
            flag = " 🔔" if o["totalPrice"] < 3900 else ""
            print(f"{o['hotel']:<28} {o['airport']:<5} {o['departure']:<13} €{o['totalPrice']:>7,.0f}  {o['nights']}N{flag}")
    print("=" * 72)

    # Top 10 overall
    print("\nTop 10 goedkoopste aanbiedingen:")
    for i, o in enumerate(sorted(all_offers, key=lambda x: x["totalPrice"])[:10], 1):
        print(f"  {i:2}. {o['hotel'][:26]:<26} {o['airport']} {o['departure']}→{o['return']}  €{o['totalPrice']:,.0f} ({o['nights']}N)")

    # Opslaan
    out_path = OUTPUT_DIR / f"check24_dates_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sorted(all_offers, key=lambda x: x["totalPrice"]), f, ensure_ascii=False, indent=2)
    print(f"\nOpgeslagen: {out_path} ({len(all_offers)} aanbiedingen)")

    if IS_GH_ACTIONS:
        write_github_summary(all_offers, timestamp)

        # GitHub Issue alleen als de beste prijs lager is dan in alle eerdere Issues
        if all_offers:
            best_all = sorted(all_offers, key=lambda x: x["totalPrice"])[0]
            prev = previous_best_price()
            if prev is not None and round(best_all["totalPrice"]) >= prev:
                print(f"  Geen Issue: €{best_all['totalPrice']:,.0f} is niet lager dan eerdere beste €{prev:,}")
                return
            create_github_issue(
                title=f"📅 Datumscanner: beste prijs = €{best_all['totalPrice']:,.0f} op {best_all['departure']} ({best_all['hotel']} / {best_all['airport']})",
                body=(
                    f"**Datumscanner resultaat** — {timestamp}\n\n"
                    f"| Hotel | Vliegveld | Vertrek | Terug | Nachten | Prijs |\n"
                    f"|---|---|---|---|---|---|\n"
                    + "\n".join(
                        f"| {o['hotel']} | {o['airport']} | {o['departure']} | {o['return']} | {o['nights']}N | **€{o['totalPrice']:,.0f}** |"
                        for o in sorted(all_offers, key=lambda x: x["totalPrice"])[:10]
                    )
                    + f"\n\n[Boek beste aanbieding]({best_all['url']})"
                ),
            )


if __name__ == "__main__":
    main()
