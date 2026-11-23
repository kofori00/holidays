# AGENT HANDOFF — Holiday Finder & Antalya Meivakantie 2027

**Last Updated:** 2026-11-23 UTC  
**Target User Context:** Family in the Netherlands (**2 Adults + 5-year-old + 0/1-year-old baby**). Strictly bound by Dutch primary-school **Meivakantie 2027: Saturday 24 April – Sunday 9 May 2027** (child returns to school Monday 10 May 2027; preferred return **Saturday 8 May 2027** → **11 nights / 12 travel days: `Tue 27 Apr → Sat 8 May 2027`**).

---

## 1. Current State & What the User Wants Next

The user narrowed down their top resort choices for **luxury + big aquapark + lots of kids/baby activities + short ~15–20 min airport transfer (Lara Beach)** to:
1. **BAYOU Lara by Barut** (`hotelId=15718`, `areaId=578`, Check24 `9.5/10`, formerly *Lara Barut Collection*) — #1 on food, renovated rooms, and Bary Star baby concept.
2. **Delphin Imperial Hotel** (`hotelId=28054`, `areaId=578`, Check24 `9.3/10`) — #1 for compact stroller walks + free Luna Park + neighboring Aqua Serenity waterpark.
3. **Delphin BE Grand Resort** (`hotelId=12975`, `areaId=578`, Check24 `9.1/10`) — #1 for massive on-site aquapark + free Luna Park.

**HOWEVER — CRITICAL UNRESOLVED ISSUE TO SOLVE NEXT:**
When the user opened our clean Check24 deep link for **BAYOU Lara by Barut** (`Tue 27 Apr → Sat 8 May 2027`, 11 nights, `A-A-5-0`, All Inclusive), **the live price in the browser jumped from ~€3,600 (cached `price-calendar` API) to €4,500+ after Check24's real-time *Vakanzprüfung* (tour-operator availability check).**

Because the originating Termux/Linux phone environment has **no Chrome / Chromium / Playwright installed**, we could NOT run headless browser verification against Check24's live post-*Vakanzprüfung* offer list or against Dutch JS-rendered sites (`Prijsvrij.nl`, `SUNtip.nl`, `Corendon.nl`, `TUI.nl`, `Sunweb.nl`).

---

## 2. Priority Tasks for the Receiving Agent (With Browser / Playwright Access)

1. **Verify TRUE Post-*Vakanzprüfung* Live Bookable Prices on Check24.de:**
   - Open the clean native Check24 URLs (see `README.md`) in Playwright/Chrome, accept the `"Geht klar"` cookie banner, wait 8–12s for live tour-operator offers to finish loading (past *"Sie können Ihren Traumurlaub innerhalb von nur 2 Minuten buchen!"*), and capture the **actual bookable price, room type, tour operator, and flight times** for:
     - **BAYOU Lara by Barut (`15718`)**
     - **Delphin Imperial (`28054`)**
     - **Delphin BE Grand (`12975`)**
     - **Rixos Sungate (`16147`, `areaId=580`)**
   - Test both **`Tue 27 Apr → Sat 8 May 2027`** (11 nights, preferred Saturday return) AND **`Sat 24 Apr → Wed 5 May 2027`** (11 nights, cheapest calendar date) across `DTM`, `DUS`, `CGN`, `FRA`, `HAM`.
   - Confirm whether **Delphin Imperial** or **Delphin BE Grand** stays closer to ~€3,700–€3,900 on live *Vakanzprüfung* than BAYOU Lara did!

2. **Check Dutch Multi-Operator Sites & Direct Tour Operators in a Real Browser:**
   - **Prijsvrij.nl:** `https://www.prijsvrij.nl/vakanties/turkije/turkse-riviera/lara/delphin-be-grand-resort` (and search `BAYOU Lara` / `Lara Barut Collection` & `Delphin Imperial`)
   - **SUNtip.nl:** `https://www.suntip.nl/vakantie/turkije/turkse-riviera/lara/delphin-be-grand-resort--34938`
   - **Corendon.nl:** `https://www.corendon.nl/turkije/turkse-riviera/antalya/lara/delphin-be-grand-resort` *(as of 2026-11-22, `monthTrips` only went through early April 2027; check if May 2027 has opened!)*
   - **TUI.nl:** `https://www.tui.nl/delphin-be-grand-resort-509697556/`
   - **Sunweb.nl:** `https://www.sunweb.nl/vakantie/turkije/turkse-riviera/antalya-lara/hotel-delphin-be-grand-resort-lara`
   - **Rule:** Never solve or bypass CAPTCHAs/Cloudflare Turnstile (`VakantieDiscounter.nl`, `Weg.de`, `Ab-in-den-Urlaub.de` returned `403` to plain HTTP). If any site shows an anti-bot gate, report it and skip.

3. **Check Unbundled (Hotel-Only + Separate Direct Flights) Benchmark:**
   - Compare **separate direct flights** (SunExpress / Corendon Airlines / Pegasus from `DTM`/`DUS`/`CGN`/`FRA`/`RTM`/`EIN` to `AYT`) + **hotel-only rate** (Barut direct / Check24 Hotel / Booking.com) vs. the live €4,500+ package price. Remind user about losing EU *Pauschalreise* / SGR / transfer bundling if booking separately.

---

## 3. Critical Technical Gotchas (Read Before Running Any Script!)

1. **Check24 `price-calendar` API = Cached Indicative Prices Only:**
   - Endpoint: `POST https://urlaub.check24.de/suche/json/offer/price-calendar` (requires `clientId` scraped from the HTML of `/suche/angebot` + `c24consent=fam` cookie).
   - It correctly parses `roomAllocation=A-A-5-0`, `catering=allinclusive`, and `days=12`, **but** returns cached batch *"ab"* prices that can jump €800–€1,000+ once the browser executes live *Vakanzprüfung*.
2. **Check24 `days` = Travel Days (`nights + 1`):**
   - `days=7` → 6 nights
   - `days=8` → 7 nights
   - `days=12` → **11 nights** (e.g. `2027-04-27 → 2027-05-08`)
   - `days=13` → **12 nights**
3. **Check24 Unsupported Airport Silent Fallback Trap:**
   - Check24 does **NOT** support `RTM`, `EIN`, or `MST`. Passing `airport=RTM` returns HTTP `200` and **silently falls back to the global cheapest airport (`Hamburg (HAM)`)**!
   - **Always inspect `offer['departureAirport']`** in the JSON response to verify the true departure airport.
   - *(Tip: Passing an invalid code like `airport=ZZZ` intentionally triggers this global-cheapest lookup and reveals the single cheapest airport on all of Check24 via `offer['departureAirport']`!)*
4. **Use Clean Native Check24 URLs:**
   - Good: `https://urlaub.check24.de/suche/angebot?airport=DTM&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=15718&areaId=578&catering=allinclusive&offerSort=price`
   - Avoid legacy query params (`verpflegung=AI&ab=...&reisezeitraum=...`) from older scripts.
5. **Resolving Check24 `hotelId` from `/hotel/tuerkei/<cms_id>` Pages:**
   - The number in `/hotel/tuerkei/7854` is a CMS slug, **NOT** the booking engine `hotelId` (`15718`).
   - Fetch `/hotel/tuerkei/...` with **standard HTML headers** (`Accept: text/html`, NO `X-Requested-With: XMLHttpRequest`, otherwise Check24 SSR throws `500` or omits links!), then regex `areaId=(\d+)&(?:amp;)?hotelId=(\d+)`.
6. **Do NOT Over-Parallelize Check24 Requests:**
   - 4+ parallel threads trigger Check24 throttling/timeouts (`HTTP 504` / connection aborts). Run sequentially with a `0.2s` sleep between calls.
7. **Display Raw URLs in User Responses:**
   - The user interacts via Termux/mobile CLI where markdown `[label](url)` hides the URL. **Always output full raw `https://...` URLs** directly in responses.
8. **Never Recommend Turkish-VPN Hotel Rates:**
   - User has NordVPN; already advised that VPN does not lower Check24 prices and booking Turkish-resident hotel-only rates with an EU passport risks surcharges at check-in.

---

## 4. Quick-Start for the Next Agent

```bash
# Inspect all saved JSON datasets from 2026-11-22
ls -lh *.json

# Run the existing Check24 calendar comparison script (indicative prices only!)
python3 scrape_rixos_both.py
```

**Note on `holiday_gui.py`:** Designed for a GPU/cloud instance running vLLM on `http://localhost:8080/v1/chat/completions` + Playwright Chromium (see `onstart.sh` / `setup.sh`). Its Check24 cheapest-deal tab intercepts `price-calendar` responses via Playwright; to get **true post-*Vakanzprüfung* prices**, wait for the live offer cards in the DOM after the loading banner finishes rather than relying solely on `price-calendar`.
