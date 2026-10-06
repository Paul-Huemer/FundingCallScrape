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
| `--only eu,ffg,austria,international,watchlist` | Run only some of the sources |
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
| **FFG** | Drupal views endpoint behind the call list (the public list page is served stale), then each call's *Steckbrief* | "Max. Förderung pro Projekt" (official) plus funding rate. FFG pages that only mirror Horizon/LIFE/Digital Europe calls are skipped, because the EU source covers them in more detail |
| **FWF** | Solr JSON API of the programme portfolio (open submissions) | "Volumen" field or detail page |
| **OeAD · Sparkling Science 2.0** | Call page + FAQ | Base maximum + raised caps |
| **aws · Proof of Concept** | Programme page (deadlines, budget-exhausted notices) | KLEIN / GROSS caps |
| **Interreg Bayern–Österreich, Österreich–Tschechien** | Deadline tables | Project size classes |
| **netidee** | Home page status; a call is only emitted when a deadline is announced | From the detail page |

| **EIT · European Institute of Innovation & Technology** | EIT opportunities aggregator: open calls of all EIT communities | From the detail page |
| **Watchlist** ([config/watchlist.json](config/watchlist.json)): 22 niche funders, see below | Each funder's announcement page is scanned for a future deadline, a "closed / no call" phrase, or fixed yearly dates | Curated from the funder's guidelines, or read from the page |

### Watchlist: non-typical funders

These funders have no call database. The scraper checks each funder's page on every run. If a deadline is announced, the funder appears as an open call. Otherwise it appears as a **Monitored** card showing the funder's usual call rhythm, so you can plan ahead.

| Dashboard group | Funders |
|---|---|
| Austrian foundations & public funds | Zukunftsfonds der Republik (rolling, ≤ €50k), Nationalfonds (1 Feb / 1 Apr / 1 Sep), Fonds Gesundes Österreich, OeNB Jubiläumsfonds (€50–300k, financial-literacy cluster only), Theodor Körner Fonds |
| Upper Austria · regional funders | AK OÖ Zukunftsfonds "Arbeit-Menschen-Digital" (≤ €200k, 50%), Land OÖ Kultur: wissenschaftliche Projekte, Land OÖ Gedenk- und Erinnerungskultur |
| Erasmus+ · OeAD (national agency) | KA220 Cooperation Partnerships SCH / HED / YOU / ADU (€120k / 250k / 400k), KA210-SCH (€30k / 60k). These are not listed on the EU portal |
| Games, EdTech & tech-industry grants | Tools Competition (EdTech, $50k–300k), Epic MegaGrants, Unity for Humanity, NLnet / NGI |
| International foundations & prizes | Prix Ars Electronica / S+T+ARTS, Jacobs Foundation CIFAR Fellowship, Japan Prize |
| Multinational programmes | CEI Know-how Exchange, Interreg Alpine Space small-scale projects |

**Adding a funder** means adding an entry to `config/watchlist.json` with `url`, `group`, `rhythm`, `amount` and `fit`. Optional fields: `deadline_patterns` (a regex with one date group), `recurring_deadlines` (`["MM-DD"]`), `rolling`, `closed_patterns` and `partner_only`. The field reference is at the top of the file.

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
* Not scrapable:
  * ÖAW Heritage Science: the site blocks automated access, so check it by hand.
  * Google.org: JS-only site.

**Left out on purpose:**
* WWTF and Wirtschaftsagentur Wien: applicants must be based in Vienna.
* Interreg Central Europe: no further call until the post-2027 programme.
* Land OÖ research calls (e.g. *Industrial AI Upper Austria*): these run through FFG eCall and appear in the FFG source.
* Creative Europe Desk Austria: duplicates the EU portal.

## How matching works

`scraper/scoring.py` scores every call from 0 to 100 against the research areas in `config/lab_profile.json`:

* Title hits count 3×. Generic words (prefixed `~`, e.g. *education*, *AI*) count 0.3×.
* Off-topic terms (batteries, nuclear, agriculture, …) subtract points.
* Instruments that suit an FH lab regardless of topic get a bonus (`programme_bonus`).
* **Educational games are the lab's core niche.** They have their own area (weight 3.5), and a `synergies` bonus applies when a call matches both games/XR and education. A smaller bonus covers games combined with museums or exhibitions.
* Watchlist funders keep a minimum score based on their curated `fit` (high ≥ 62, medium ≥ 42, low ≥ 22).
* If research institutions or FHs are not listed as applicants (e.g. FFG company-only schemes), the call is marked **Partner role only** and its score is multiplied by 0.6.

Calls scoring under 20 are dropped. The dashboard shows ≥ 60 as *Strong*, ≥ 40 as *Good* and ≥ 20 as *Possible*. To tune the matching, edit the JSON: add terms, change weights or extend the EU search terms.

## Dashboard features

The design follows [digitalmedialab.at](https://digitalmedialab.at): a white header, Inter, black type, soft white cards, and research-area tags in the site's pastel colours. The public site carries no DML logo and no lab profile.

* **Filter sidebar** (on narrow screens, the **Filter** button opens it as a sheet). It holds every filter:
  * **Research area:** the six areas from [digitalmedialab.at/research](https://digitalmedialab.at/research), each with its colour and point-and-line icon. Selecting an area shows every call in any of its topics: Visual Computing (computer vision), Intelligent Web Applications (AI & LLMs), Games and Playful Experiences (serious games, educational games, installations & heritage), User Interfaces (HCI & UX, XR), Smart and Tangible, and Data Visualization. Areas with several topics open sub-pills to narrow down. Education, Society & health and Topic-open are listed below as *cross-cutting themes*. Alt-click selects only one area. The selection is remembered in each browser. Link: `?topic=ai&topic=hci`. The area grouping lives in `AREAS` at the top of `dashboard/app.js`.
  * **Time left**: the minimum time until the deadline (≥ 1, 2, 3 or 6 months), so you only see calls you can still prepare for. Calls without a fixed deadline (rolling, opening soon, monitored) are always kept. Plus the minimum **amount per project**.
  * Checkboxes for *Lab can apply directly*, *New this week*, *Starred* and *Monitored funders*.
  * **Sources**, in four foldable categories with counts. Hover a source and click **only** to show just that one.
* **Toolbar:** search (press `/`), sort (deadline, best fit, newest, amount, source, title), the cards/table toggle and CSV export. Sorting by *Source* adds a heading per source.
* **Fit cutoff:** only calls with a fit score of **65 or more** are listed (`FIT_MIN` in `dashboard/app.js`). *Show N lower-fit calls* at the end of the list reveals the rest below a divider, marked *Lower fit · score*. The same button hides them again.
* **Active filters:** a line above the results shows the count and each active filter as a chip. Click a chip to remove it.
* **Cards:** deadline, source, title, a two-line summary, a coloured tag for each DML research area the call fits (grey tags for cross-cutting themes), and the time left. Calls closing within 30 days are shown in red or orange. *Partner role only* only appears when it applies. Funding **per project** sits on the right, and "≈" marks an amount estimated from the text. When a funder states only the budget for the whole call, that total is shown greyed out with an amber **Total budget · not per project** label (also in the table and the detail panel). The per-project amount filter and the *Amount* sort ignore these totals; that sort lists per-project amounts first, then total-only calls. Click a card for its details. Monitored funders have dashed cards that show their usual call rhythm.
* **Detail drawer:** funding and deadline facts, summary, why the call fits, who can apply, research areas, the official call link and a collapsible excerpt of the call text. Deep links work, e.g. `index.html#call=eu:CREA-MEDIA-2027-DEVVGIM`.
* **Link options:** `?q=lernspiel`, `?source=Erasmus` (repeatable, prefix match), `?view=table`, `?sort=fit|newest|amount|deadline|title|source`.
* **Other:** stars are saved per browser; mobile layout.

## Known limits

* Some EU topics (e.g. Creative Europe lump sums, MSCA unit costs) state the per-project amount only in the call-document PDF. These show **Not stated – see call document**. AI summaries do not invent amounts.
* Scrapers depend on page structure. A broken source is logged (see the workflow run under *Actions*, or the console locally), recorded under `sources_report` in `data/calls.json`, and does not stop the other sources.
