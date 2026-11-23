# Holiday Scraper & Antalya 2027 Family Resort Research (`holidays`)

> **For AI Agents Picking Up This Repo:** Read [`AGENT_HANDOFF.md`](./AGENT_HANDOFF.md) first — it contains critical technical gotchas (including Check24's cached `price-calendar` vs. live *Vakanzprüfung* discrepancy, airport fallback traps, and exact next steps).

---

## 1. Family Profile & Hard Constraints

- **Travelers:** 2 Adults + 2 Children — **5-year-old** + **0/1-year-old baby** (`roomAllocation=A-A-5-0`; age `0` and `1` are both priced as infant `<2` on Check24, verify exact birthdates at checkout)
- **Board Basis:** All Inclusive / Ultra All Inclusive (`catering=allinclusive` / `AI`)
- **Hard School-Holiday Window (Dutch *Leerplicht* — 5yo):**
  - **Official Dutch Meivakantie 2027 (2-week primary school window):** **Saturday 24 April 2027 – Sunday 9 May 2027**
  - **School resumes:** Monday 10 May 2027
  - **Preferred Return Date:** **Saturday 8 May 2027** (full Sunday at home to unpack/rest)
  - **Preferred Duration:** **11 nights / 12 travel days** → **`Tue 27 Apr 2027 → Sat 8 May 2027`** (`days=12` on Check24)
- **Resort Priorities:**
  1. Genuine 5-star luxury (great food, renovated/clean rooms)
  2. Lots of kids' activities (supervised Mini Club for 5yo + baby-friendly amenities for 1yo)
  3. Strong aquapark / water slides (heated pools helpful in late April/early May)
  4. Short airport transfer (~15–20 min Lara Beach preferred over 50–65 min Kemer)
  5. Best value for money (German border airports `DTM`, `DUS`, `CGN`, `FRA`, `HAM`, `HAJ`, `BRE` beat `AMS` by €800–€1,800 during Dutch Meivakantie)

---

## 2. Shortlisted Top Resorts (Verified IDs, Reviews & Indicative 11-Night Prices)

> **IMPORTANT PRICE CAVEAT:** All prices in the JSON files below were pulled live on **2026-11-22** from Check24's `price-calendar` API (`POST https://urlaub.check24.de/suche/json/offer/price-calendar`). **These are cached indicative *"ab"* (starting-from) prices.** In real browser testing by the user, opening the BAYOU Lara `DTM`/`DUS` link triggered Check24's live tour-operator *Vakanzprüfung*, where the actual bookable price jumped from ~€3,504–€3,678 to **€4,500+**. Always confirm real bookable checkout prices in a real browser!

### Verified Check24 Hotel Registry

| Resort | Area (Transfer from AYT) | Check24 `hotelId` | `areaId` | Check24 Rating | 11n Indicative (`Tue 27 Apr → Sat 8 May`, `HAM` / `DTM` / `DUS`) | Highlights & Honest Cons |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **BAYOU Lara by Barut** *(formerly Lara Barut Collection)* | Lara (~15–20m) | `15718` | `578` | **9.5/10** (566 rev) | €3,192 / €3,504 / €3,678 *(jumped to €4,500+ on live browser check!)* | Best food (*Zestful Bazaar* + ~9 à la cartes), fully renovated modern rooms, **Bary Star baby concept (0–3)**, Mini Club (4–12), 8 slides + kids splash pools, sandy beach, pharmacies 5–10 min walk. **Con:** No Luna Park; 1yo needs parent in soft-play; live price jump! |
| **Delphin Imperial Hotel** | Lara (~15–20m) | `28054` | `578` | **9.3/10** (3,155 rev) | €3,523 / €3,778 / €4,111 | Compact vertical layout (**short buggy walks**), free **on-site Luna Park (fairground)**, Mini Club (4–12), free access to neighboring *Delphin Aqua Serenity* waterpark (8 big + 7 kids slides + lazy river). **Con:** Waterpark is right next door rather than central. |
| **Delphin BE Grand Resort** | Lara (~15–20m) | `12975` | `578` | **9.1/10** (2,569 rev) | €3,531 / €3,786 / €4,083 | Massive **on-site aquapark** (9 big + 7 kids slides) + free **on-site Luna Park**, heated kids/relax/indoor pools, Mini Club (4–12), sandy beach. **Con:** Huge 800+ room sprawl (long walks with stroller), some room blocks noisy/dated. |
| **Rixos Sungate** | Kemer / Beldibi (~55m) | `16147` | `580` | *(not in offer JSON)* | ~€3,259–€3,707 (24 Apr–9 May best) | Rixy Kids Club + 8–13 slides + **free Land of Legends entry & shuttle**, lowest price among Rixos. **Con:** Pebble beach, aging indoor wear & tear, ~55–65 min transfer. |
| **Papillon Zeugma Relaxury** | Belek (~35–45m) | `9848` | `578` | **8.9/10** (446 rev) | ~€3,661–€4,098 (24 Apr–9 May best) | Refined luxury, great food, lazy river, heated outdoor pool, Papy Kids Club. **Con:** Smaller/more compact slide selection. |
| **Land of Legends Nickelodeon Hotel** | Belek / Kadriye (~30m) | `1997328` | `578` | **8.7/10** (44 rev) | ~€3,748–€4,092 (24 Apr–9 May best) | Direct access + early entry to Land of Legends mega theme/water park; PAW Patrol/SpongeBob rooms. **Con:** Not beachfront, "loud, bright & chaotic" with a baby, strict buffet hours. |
| **Ela Excellence Resort Belek** | Belek (~35–45m) | `18693` | `578` | **8.9/10** (179 rev) | ~€4,506–€4,752 (24 Apr–9 May best) | **Everland Kids World** (elite kids + baby facilities), heated outdoor pool, calmer luxury. **Con:** Pricier. |
| **Rixos Premium Belek** | Belek (~35–45m) | `14852` | `578` | **9.1/10** (572 rev) | €5,596+ (Apr 15 window; benchmark) | Ultra-luxe + Land of Legends + 700m sandy beach. **Con:** ~2x the price of Sungate/Delphin/Barut. |
| **Limak Arcadia Sport Resort** | Belek (~40m) | `5364` | `578` | **8.6/10** (2,018 rev) | €2,247 `HAM` / €2,669 `DTM` / €2,704 `DUS` (24 Apr–9 May) | Strong budget 5-star value, less ultra-luxe than Barut/Delphin. |
| **BAYOU Lara Luxury Suites & Villas** | Lara (~15–20m) | `1860212` | `578` | **9.1/10** (21 rev) | €4,882 `HAM` / €5,444 `DTM` / €5,409 `DUS` | Separate private heated-pool villa enclave inside BAYOU Lara grounds. |

---

## 3. Clean Native Check24 Deep Links (`Tue 27 Apr → Sat 8 May 2027`, 11 Nights)

**BAYOU Lara by Barut (`hotelId=15718`):**
- `HAM`: `https://urlaub.check24.de/suche/angebot?airport=HAM&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=15718&areaId=578&catering=allinclusive&offerSort=price`
- `FRA`: `https://urlaub.check24.de/suche/angebot?airport=FRA&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=15718&areaId=578&catering=allinclusive&offerSort=price`
- `DTM`: `https://urlaub.check24.de/suche/angebot?airport=DTM&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=15718&areaId=578&catering=allinclusive&offerSort=price`
- `DUS`: `https://urlaub.check24.de/suche/angebot?airport=DUS&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=15718&areaId=578&catering=allinclusive&offerSort=price`
- `CGN`: `https://urlaub.check24.de/suche/angebot?airport=CGN&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=15718&areaId=578&catering=allinclusive&offerSort=price`
- `AMS`: `https://urlaub.check24.de/suche/angebot?airport=AMS&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=15718&areaId=578&catering=allinclusive&offerSort=price`
- Hotel Page: `https://urlaub.check24.de/hotel/tuerkei/7854`

**Delphin BE Grand (`hotelId=12975`, `DTM`):**
- `https://urlaub.check24.de/suche/angebot?airport=DTM&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=12975&areaId=578&catering=allinclusive&offerSort=price`

**Delphin Imperial (`hotelId=28054`, `DTM`):**
- `https://urlaub.check24.de/suche/angebot?airport=DTM&transportType=flight&roomAllocation=A-A-5-0&departureDate=2027-04-27&returnDate=2027-05-08&days=12&hotelId=28054&areaId=578&catering=allinclusive&offerSort=price`

---

## 4. Complete File Inventory

### Python Scrapers & App
| File | Purpose |
| :--- | :--- |
| `scrape_rixos_both.py` | Reusable Check24 `price-calendar` scraper comparing Rixos Premium Belek (`14852`) & Rixos Sungate (`16147`) across all 4 saved 2027 holiday windows (`7d`) + Meivakantie (`11d`/`12d`). |
| `scrape_rixos_sungate.py` | Original single-hotel Check24 scraper for Rixos Sungate (`7d` across 4 saved 2027 windows). |
| `scrape_rixos_meivakantie.py` | Original single-hotel Check24 scraper for Rixos Sungate (`11d` & `12d` Meivakantie 2027). |
| `run_herfstvakantie_scrape.py` | Legacy Oct 2026 multi-country Check24 scraper (`10.10.2026–18.10.2026`). |
| `holiday_gui.py` | Flask + Playwright + local vLLM (`localhost:8080`) web GUI supporting Check24, TUI, Corendon, Alltours, DERTOUR. |
| `setup.sh`, `onstart.sh` | Cloud/Vast.ai bootstrap scripts for running `holiday_gui.py` with Playwright + Chromium on port 5001. |

### Saved JSON Datasets (All Scraped Live on `2026-11-22` Unless Noted)
| File | Contents |
| :--- | :--- |
| `bayou_lara_11n_meivakantie_2027.json` | BAYOU Lara by Barut (`15718`) 11-night indicative prices across 12 airports (`HAM`–`AMS`) strictly inside `24 Apr – 9 May 2027`. |
| `comparable_resorts_11n_meivakantie_2027.json` | Live 11-night comparison of Lara/Belek/Kemer peers (BAYOU Lara, Delphin Imperial, Delphin BE Grand, Melas Lara, Titanic Deluxe Lara, Limak Arcadia, Rixos Tekirova, etc.) inside `24 Apr – 9 May 2027`. |
| `delphin_be_grand_11n_all_airports.json` | 20-airport sweep (`AMS`–`SCN`) for Delphin BE Grand 11 nights inside `24 Apr – 9 May 2027` *(note: ignore `RTM` entries — Check24 fell back to `HAM`!)*. |
| `delphin_be_grand_meivakantie_airports.json` | 9-airport sweep (`FRA`, `DTM`, `DUS`, `CGN`, `FMO`, `NRN`, `BRU`, `AMS`, `EIN`) for Delphin BE Grand 10/11/12 nights inside Meivakantie 2027. |
| `delphin_be_grand_deals.json` | 1,377 offers for Delphin BE Grand across all 4 saved 2027 holiday windows (`Meivakantie`, `June`, `Zomervakantie`, `Herfstvakantie`) × `DUS`/`CGN`/`AMS`. |
| `top5_strict_meivakantie_2027.json` | Head-to-head 11n & 12n prices strictly inside `24 Apr – 9 May 2027` (+ `1–16 May` alt window) for Delphin BE Grand, Rixos Sungate, Papillon Zeugma, Nickelodeon Hotel, Ela Excellence. |
| `meivakantie_24apr_2may_2027.json` | Mandatory 1-week window (`24 Apr – 2 May 2027`, 6n/7n/8n) comparison across Top 5 resorts. |
| `belek_12night_comparison.json` | Top Belek 5-star resorts vs. Rixos Sungate & Rixos Premium Belek (`11n`/`12n`, flexible Apr 15 window). |
| `luxe_aquapark_12night_deals.json` & `luxe_aquapark_belek_extra.json` | Live 11n/12n price & Check24 rating checks for luxury aquapark resorts (Ela Excellence, Granada Luxury, Titanic Luxury Collection, Selectum Luxury, Delphin BE Grand). |
| `rixos_premium_belek_deals.json` & `rixos_premium_belek_meivakantie_11_12_nights.json` | 400 (7d) + 186 (11d/12d) offers for Rixos Premium Belek (`14852`). |
| `rixos_sungate_deals.json`, `rixos_sungate_meivakantie_11_12_nights.json`, `rixos_comparison_summary.json` | 400 (7d) + 186 (11d/12d) offers for Rixos Sungate (`16147`) + comparison run metadata. |
| `rixos_sungate_single_mother_deals.json` | Older Nov 9, 2026 scrape for 1 adult (`roomAllocation=A`) at Rixos Sungate. |
| `herfstvakantie_deals.json` | Older Oct 27, 2026 scrape for Herfstvakantie 2026 multi-country deals. |
