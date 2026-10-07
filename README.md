# DML Funding Radar

This tool scrapes research and project funding calls and keeps those that fit the **Digital Media Lab (FH OÖ Hagenberg)**. Each call gets a short summary, a fit score and the funding amount per project. The dashboard sorts calls by submission deadline and lets you filter by research area and source.

* **Lab profile:** [LAB_PROFILE.md](LAB_PROFILE.md) (readable) and [config/lab_profile.json](config/lab_profile.json) (used for matching)
* **Dashboard:** the shared site `https://paul-huemer.github.io/FundingCallScrape/`, or locally: double-click **`run.bat`** (it opens `dashboard/index.html`).
* **Data:** `data/calls.json` (the calls, lab profile and run report; the dashboard's `dashboard/data.js` gets only the calls and topics) and `data/history.json`, which records when each call was first found.

## Getting the newest calls

**Automatically:** the GitHub workflow `.github/workflows/update.yml` runs every **Monday at 05:00 UTC** (07:00 Vienna summer time, 06:00 winter time).
* It runs the scraper on GitHub's servers, commits the refreshed data and republishes the GitHub Pages site.
* Repository members can also start it by hand: *Actions → Update funding calls → Run workflow* (about 10 minutes).
* New calls get a black **New** badge for a week. *Filter → New this week* (or the link under the page title) shows only those.

**Locally:** `run.bat update` fetches everything fresh (5–7 minutes), then opens the dashboard. Without the batch file:

```bash
python -m scraper.main --fresh
```

## Sharing with colleagues (GitHub Pages)

The code is already on GitHub in the repository `Paul-Huemer/FundingCallScrape`. The site goes live after this one-time setup on github.com:
1. **Settings → Pages → Build and deployment → Source: "GitHub Actions".**
2. *Optional:* **Settings → Secrets and variables → Actions → New repository secret** `ANTHROPIC_API_KEY`, for English AI summaries. The key is stored encrypted by GitHub and is never written to the repository or the site.
3. **Actions → Update funding calls → Run workflow** once. The site then appears at `https://paul-huemer.github.io/FundingCallScrape/`. Until then, that link shows "404".

After that, every push to `main` that changes `dashboard/` republishes the site, and the Monday run refreshes the data.

### What is public

**The repository is public.** Everything committed can be read by anyone on github.com and may be indexed by search engines:
* The code, the configuration and the lab profile (`LAB_PROFILE.md`, `config/lab_profile.json`), including the research partners, past funders and the "which calls fit us best" priorities.
* The scraped data (`data/calls.json`, `dashboard/data.js`, `data/history.json`).

**The site is public too.** It contains only the `dashboard/` folder (HTML, CSS, JS and `data.js`): no DML logo, no lab profile, no run report. `data.js` holds just the update date, the topic list and the calls. Anyone with the link can open it, but the page asks search engines not to index it (`noindex`).

What is kept out:
* **Contact details:** e-mail addresses and phone numbers of contact persons on funders' pages are removed before the data is written (`public_record()` in `scraper/main.py`). The rest of the data is public information from the funders' websites.
* **Funders' text:** the verbatim *Call text (excerpt)* is published only for sources whose terms allow reuse: EU portal (CC BY 4.0, not cascade calls), EIT, FWF (CC BY 4.0), OeAD, EUREKA and Wellcome. Each excerpt carries a source credit. For everyone else the data holds only title, link, dates, amount and our own summary (`EXCERPT_LICENCES` in `scraper/main.py`; terms checked 2026-10-06). Add a host there only after reading its terms.

### Rules for fetching

* **robots.txt is obeyed.** `Http` in `scraper/common.py` reads each site's robots.txt (including `*` wildcards) and refuses disallowed URLs with `RobotsDisallowed`; it also honours `Crawl-delay`. A source that needs a disallowed URL has to be rewritten, or the site operator has to agree in writing (then pass `permitted=True` and note who agreed and when).
* **Honest User-Agent:** `DML-Antragsscraper/1.0` with a link to this repository, not a browser disguise.
* **Sites whose terms forbid bots** (Unity, Epic, Amazon) are not fetched: their watchlist entries carry `"no_fetch": true` and a `no_fetch_reason`.
* **EuroAccess is not used:** its terms forbid storing or republishing its database without EuroVienna's consent.
* **Secrets:** no API keys are stored in the code. The Anthropic key comes from your environment variable locally, or from the encrypted repository secret on GitHub.
* **Not committed (`.gitignore`):** the 300 MB page cache, local Claude/editor settings, Python caches, and any `.env` or key files.
* **Personal settings:** research-area selection, stars and view settings are stored only in each person's browser.

To keep the lab profile and data private, make the repository private (**Settings → General → Danger Zone → Change visibility**). GitHub Pages for a private repository needs a paid plan (GitHub Pro, Team or Enterprise), and the site itself stays public unless you use GitHub Enterprise Cloud's access control.

### Setup and options

```bash
pip install -r requirements.txt
```

| Command | Effect |
|---|---|
| `run.bat` | Open the dashboard; `run.bat update` refreshes the data first |
| `python -m scraper.main` | Update using the 12-hour HTTP cache (fast when re-running) |
| `--fresh` | Ignore the cache and refetch every page (what the weekly run does) |
| `--no-ai` | Skip the Claude API; use extractive summaries |
| `--only eu,ffg,austria,international,aggregators,watchlist` | Run only some of the sources |
| `-v` | Debug logging |

### AI summaries (optional, recommended)

Without credentials, the summary is the first informative sentences of the call text, so it is in German for FFG and OeAD calls. Set an API key to get English summaries from Claude, plus a "why it fits the lab" line and a second check on the per-project amount:

```bash
setx ANTHROPIC_API_KEY "sk-ant-..."
```

Results are cached in `data/cache/summaries.json`. Later runs only pay for new or changed calls (about 170 calls on the first run). The model is `claude-opus-5-5` at low effort; override it with `DML_SUMMARY_MODEL`.

## Sources

| Group in dashboard | How it is scraped | Amount per project |
|---|---|---|
| **EU · Horizon Europe / Creative Europe / Erasmus+ / Digital Europe / CERV / …** | EU Funding & Tenders Portal search API. 40 lab-specific search terms; only open and forthcoming topics with a future deadline | `budgetOverview` min/max contribution per grant (official), or call budget ÷ expected grants, or text ("EU contribution of between EUR 3 and 5 million") |
| **EU · Cascade funding** | Same API, third-party open calls run by EU projects (FSTP) | From text |
| **FFG** | robots.txt blocks the paged call list, so the source starts from the first page of `/foerderungen` and `/en/fundings` and follows the *Weitere Angebote* links on each call page, then reads each call's *Steckbrief*. This finds only part of FFG's calls (about 13 of 60 relevant ones in October 2026): check ffg.at for the rest. `FFG_LISTING_PERMITTED` in `scraper/sources/ffg.py` restores the full list once FFG agrees | "Max. Förderung pro Projekt" (official) plus funding rate. FFG pages that only mirror Horizon/LIFE/Digital Europe calls are skipped, because the EU source covers them in more detail |
| **FWF** | Solr JSON API of the programme portfolio (open submissions) | "Volumen" field or detail page |
| **OeAD · Sparkling Science 2.0** | Call page + FAQ | Base maximum + raised caps |
| **aws · Proof of Concept** | Programme page (deadlines, budget-exhausted notices) | KLEIN / GROSS caps |
| **Interreg Bayern–Österreich, Österreich–Tschechien** | Deadline tables | Project size classes |
| **netidee** | Home page status; a call is only emitted when a deadline is announced | From the detail page |

| **EIT · European Institute of Innovation & Technology** | EIT opportunities aggregator: open calls of all EIT communities | From the detail page |
| **Open calls · On the Move** | Worldwide arts & culture mobility calls, read only from the lab-related category pages (digital / new media, technology, art & science, cultural heritage, education, disability); scoring drops the rest | From the call text |
| **Open calls · S+T+ARTS** | The EC's science-technology-arts calls page (residencies, open calls) | From the call text |
| **Open calls · EUREKA** | Open Eurostars, EUREKA Cluster (ITEA, CELTIC-NEXT, …) and Network Project calls that Austria takes part in. Company-led, so marked *Partner role only*; pitch sessions are skipped | National funding through FFG |
| **Watchlist** ([config/watchlist.json](config/watchlist.json)): 68 niche funders, see below | Each funder's announcement page is scanned for a future deadline, a "closed / no call" phrase, or fixed yearly dates | Curated from the funder's guidelines, or read from the page |

### Watchlist: non-typical funders

These funders have no call database. The scraper checks each funder's page on every run. If a deadline is announced, the funder appears as an open call. Otherwise it appears as a **Monitored** card showing the funder's usual call rhythm, so you can plan ahead.

| Dashboard group | Funders |
|---|---|
| Austrian ministries & federal programmes | Josef Ressel Zentren (CDG, built for FHs, ≤ €460k/year for 5 years), OeAD Citizen Science Award, BMWKMS Medienkunst (Feb / Aug) and "Digitale Transformation" (≤ €50k), BMFWF calls for Hochschulen (FH-Sondermittel), Ars Docendi, OeAD Kulturvermittlung mit Schulen, Africa-UniNet, Bundes-Jugendförderung, Digital Überall, LBG Open Innovation in Science |
| Austrian foundations & public funds | Zukunftsfonds der Republik (rolling, ≤ €50k), Nationalfonds (1 Feb / 1 Apr / 1 Sep), Fonds Gesundes Österreich, OeNB Jubiläumsfonds (€50–300k, financial-literacy cluster only), Theodor Körner Fonds, Dr. Maria Schaumayer Stiftung |
| Upper Austria · regional funders | LEADER Mühlviertler Kernland (Hagenberg is a member municipality; about two calls a year), Land OÖ out-of-school education for sustainable development (65%, ≤ €25k, rolling; Hochschulen eligible), Land OÖ Horizon Europe "Antragsfit" (≤ €25k), Land OÖ new research fields, Land OÖ cluster cooperation (partner), Oö. Landespreis für Innovation, AK OÖ Zukunftsfonds "Arbeit-Menschen-Digital" (≤ €200k, 50%), Land OÖ Kultur: wissenschaftliche Projekte, Kinder- und Jugendkultur, Medienprojekte, Land OÖ Gedenk- und Erinnerungskultur |
| Upper Austria · City of Linz | "LINZ fördert Wissenschaft" (rolling), Linz Kultur programmes incl. LINZ_media_arts (April), congress and event funding (≤ €3k) |
| European partnerships & networks | Resilient Cultural Heritage Partnership (first calls 2026/27), THCS health & care, Biodiversa+ (via FWF), EP BrainHealth, CHIST-ERA, Eurostars-3, Culture Moves Europe (residency hosts) |
| Call databases (browse manually) | Interreg.eu, ERA-LEARN, Heritage Research Hub, OnePass (FundingBox cascade calls), Digital Skills & Jobs Platform. These sites need JavaScript or list too broadly, so the dashboard shows them as monitored links to browse |
| Erasmus+ · OeAD (national agency) | KA220 Cooperation Partnerships SCH / HED / YOU / ADU (€120k / 250k / 400k), KA210-SCH (€30k / 60k). These are not listed on the EU portal |
| Games, EdTech & tech-industry grants | Tools Competition (EdTech, $50k–300k), Epic MegaGrants, Unity for Humanity, NLnet / NGI, aws Creative Impact (games studios lead; Austria has no federal games funding), Amazon Research Awards, Google Academic Research Awards, Anthropic AI for Science (API credits) |
| International foundations & prizes | Prix Ars Electronica / S+T+ARTS, Jacobs Foundation CIFAR Fellowship, Japan Prize, Wikimedia Research Fund, Mozilla Foundation, European Media and Information Fund (disinformation), Wellcome mental health, Zero Project Awards (accessibility) |
| Multinational programmes | CEI Know-how Exchange, Interreg Alpine Space small-scale projects, EUREGIO Bayerischer Wald–Böhmerwald small-project funds, Interreg Danube |

**Adding a funder** means adding an entry to `config/watchlist.json` with `url`, `group`, `rhythm`, `amount` and `fit`. Optional fields: `deadline_patterns` (a regex with one date group; a date without a year means its next occurrence), `recurring_deadlines` (`["MM-DD"]`), `rolling`, `closed_patterns`, `partner_only` and `no_fetch` (list the funder from the entry alone, for PDF, JavaScript-only or bot-blocking pages). The field reference is at the top of the file.

**Researched but not added:**
* Not open to the lab, or not funding project work:
  * AK Wien Digifonds: ended in 2023.
  * RTR funds: for broadcasters and media companies only.
  * Innovationsstiftung für Bildung: no open grant call.
  * Klimaschulen / KLAR!: regions and schools apply.
  * Prototype Fund: Germany only.
  * NVIDIA academic grants: the host must award PhDs.
  * Roblox, Niantic, Xbox: no fitting programmes.
  * VolkswagenStiftung: only as partner of a German lead.
  * Visegrad Fund: needs three V4 partners.
  * DIGITAL.PLUS, Stadt Linz start-up grants: companies and start-ups only.
  * Creative Region Linz & Upper Austria, tech2b, Factory300: networking and incubation, no funding calls.
  * Gesundheitsfonds OÖ, Education Group, Bildungsdirektion OÖ, OÖ bank and utility foundations: no competitive public calls.
  * LBG clinical research groups: medical universities only. Licht ins Dunkel: excludes research costs. Karl Kahane Foundation: existing partners only.
  * Fondation Botnar (8 focus countries), Pro Helvetia and Creative Industries Fund NL (Swiss or Dutch lead), EEA/Norway Grants (expert partner at most), Schmidt AI2050 (nomination only), LEGO Foundation (no open call).
* Ended or paused:
  * CHANSE (ended Aug 2026), ÖAW go!digital (last call 2021), APPEAR (next call not before late 2027), EUSDR seed money (last 2023–24).
  * Federal games funding: does not exist in Austria (checked against the 2025–29 government programme); aws Creative Impact is the closest instrument.
* Not scrapable:
  * ÖAW Heritage Science: the site blocks automated access, so check it by hand.
  * Epic MegaGrants, Unity for Humanity, Amazon Research Awards (terms forbid bots) and Anthropic, Mozilla Foundation, Gulbenkian EMIF (refuse bot requests): listed from the curated entry only (rhythm and usual dates); open the page to see the current deadline.
  * Google.org: JS-only site.

**Left out on purpose:**
* WWTF and Wirtschaftsagentur Wien: applicants must be based in Vienna.
* Interreg Central Europe: no further call until the post-2027 programme.
* EuroAccess (EuroVienna's call database): its terms forbid reuse without consent. Interreg Danube and Alpine Space stay on the watchlist; interreg.eu lists the rest (Interreg Europe, Central Europe, …).
* Land OÖ research calls (e.g. *Industrial AI Upper Austria*): these run through FFG eCall and appear in the FFG source.
* Creative Europe Desk Austria: duplicates the EU portal.

## How matching works

`scraper/scoring.py` scores every call from 0 to 100 against `config/lab_profile.json`. **No research area is favoured:** the tool is meant for everyone in the lab.

* **Six research areas, one weight.** Calls are scored per research area of the lab (Visual Computing, Intelligent Web Applications, Games and Playful Experiences, User Interfaces, Smart and Tangible, Data Visualization; `research_areas`). Every area has the same weight (`scoring.area_weight`) and the same cap. An area that bundles several topics (e.g. Games: serious games, educational games, installations & heritage) counts each matched term once, so it can't outscore the others by having more topics.
* **Cross-cutting themes** (Education, Society & health, Topic-open) share one lower weight (`scoring.theme_weight`). They add to a call's score but are not research areas themselves.
* Title hits count 3×. Generic words (prefixed `~`, e.g. *education*, *AI*, *visualisation*) count 0.3×.
* Off-topic terms (batteries, nuclear, agriculture, …) subtract points.
* Instruments that suit an FH lab regardless of topic get a bonus (`programme_bonus`).
* The `synergies` rules only add tags (e.g. a games call that also hits education is tagged *Educational games*); they add no points.
* Watchlist funders keep a minimum score based on their curated `fit` (high ≥ 66, medium ≥ 56, low ≥ 30), so high and medium funders clear the dashboard cutoff of 55 and are listed by default. Their fit levels and texts are written for all research areas, not one.
* If research institutions or FHs are not listed as applicants (e.g. FFG company-only schemes), the call is marked **Partner role only** and its score is multiplied by 0.6.
* The EU portal is searched with terms from every research area (`eu_search_terms`), so each area's calls are collected in the first place.

Calls scoring under 20 are dropped, and the dashboard lists calls from 55 up. To tune the matching, edit the JSON: add terms to an area, change `area_weight` / `theme_weight`, or extend the EU search terms. Keep the areas comparable: when you add terms or search terms for one area, check the others.

## Dashboard features

The design follows [digitalmedialab.at](https://digitalmedialab.at): a white header, Inter, black type, soft white cards, and research-area tags in the site's pastel colours. The public site carries no DML logo and no lab profile.

* **Filter sidebar** (on narrow screens, the **Filter** button opens it as a sheet). It holds every filter:
  * **Research area:** the six areas from [digitalmedialab.at/research](https://digitalmedialab.at/research), each with its colour and point-and-line icon. Selecting an area shows every call in any of its topics: Visual Computing (computer vision), Intelligent Web Applications (AI & LLMs), Games and Playful Experiences (serious games, educational games, installations & heritage), User Interfaces (HCI & UX, XR), Smart and Tangible, and Data Visualization. Areas with several topics open sub-pills to narrow down. Education, Society & health and Topic-open are listed below as *cross-cutting themes*. Alt-click selects only one area. The selection is remembered in each browser. Link: `?topic=ai&topic=hci`. The area grouping lives in `AREAS` at the top of `dashboard/app.js`.
  * **Time left**: the minimum time until the deadline (≥ 1, 2, 3 or 6 months), so you only see calls you can still prepare for. Calls without a fixed deadline (rolling, opening soon, monitored) are always kept. Plus the minimum **amount per project**.
  * Checkboxes for *Lab can apply directly*, *New this week*, *Starred* and *Monitored funders*.
  * **Sources**, in four foldable categories with counts. Hover a source and click **only** to show just that one.
* **Toolbar:** search (press `/`), sort (deadline, best fit, newest, amount, source, title), the cards/table toggle and CSV export. Sorting by *Source* adds a heading per source.
* **Fit cutoff:** only calls with a fit score of **55 or more** are listed (`FIT_MIN` in `dashboard/app.js`). *Show N lower-fit calls* at the end of the list reveals the rest below a divider, marked *Lower fit · score*. The same button hides them again.
* **Active filters:** a line above the results shows the count and each active filter as a chip. Click a chip to remove it.
* **Cards:** deadline, source, title, a two-line summary, a coloured tag for each DML research area the call fits (grey tags for cross-cutting themes), and the time left. Calls closing within 30 days are shown in red or orange. *Partner role only* only appears when it applies. Funding **per project** sits on the right, and "≈" marks an amount estimated from the text. When a funder states only the budget for the whole call, that total is shown greyed out with an amber **Total budget · not per project** label (also in the table and the detail panel). The per-project amount filter and the *Amount* sort ignore these totals; that sort lists per-project amounts first, then total-only calls. Click a card for its details. Monitored funders have dashed cards that show their usual call rhythm.
* **Detail drawer:** funding and deadline facts, summary, why the call fits, who can apply, research areas, the official call link and, where the funder's terms allow it, a collapsible excerpt of the call text with a source credit. Deep links work, e.g. `index.html#call=eu:CREA-MEDIA-2027-DEVVGIM`.
* **Link options:** `?q=lernspiel`, `?source=Erasmus` (repeatable, prefix match), `?view=table`, `?sort=fit|newest|amount|deadline|title|source`.
* **Other:** stars are saved per browser; mobile layout.

## Known limits

* Some EU topics (e.g. Creative Europe lump sums, MSCA unit costs) state the per-project amount only in the call-document PDF. These show **Not stated – see call document**. AI summaries do not invent amounts.
* Scrapers depend on page structure. A broken source is logged (see the workflow run under *Actions*, or the console locally), recorded under `sources_report` in `data/calls.json`, and does not stop the other sources.
