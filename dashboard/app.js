/* Funding Radar – renders window.DML_DATA (written by `python -m scraper.main`). */
(() => {
  "use strict";

  const DATA = window.DML_DATA || { calls: [], generated_at: null, topics: [] };
  const DAY = 86400000;
  const FIT_MIN = 55;           // calls scoring below this stay hidden until "Show lower-fit calls"
  const TODAY = new Date(new Date().toDateString());

  // ------------------------------------------------------------------ storage (per-viewer conveniences only)
  const store = {
    get(k, d) { try { const v = localStorage.getItem("dml-" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("dml-" + k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  const state = {
    q: "",
    showLow: false,              // reveal calls under FIT_MIN (button at the end of the list)
    window: "all",
    minAmount: "0",
    showWatch: true,
    directOnly: false,
    starredOnly: false,
    newOnly: false,
    sources: new Set(),          // explicit selection; empty = all sources
    topics: new Set(store.get("topics", [])),   // lab research areas (OR); remembered per browser = "my focus"
    view: store.get("view", "cards") === "table" ? "table" : "cards",
    sortBy: store.get("sort", "deadline"),   // deadline | fit | newest | amount | title | source
    sortDir: 1,                               // -1 reverses (table header second click)
    stars: new Set(store.get("stars", [])),
  };

  // ------------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const parseDate = (s) => (s ? new Date(s + "T00:00:00") : null);
  const daysLeft = (c) => (c.deadline ? Math.round((parseDate(c.deadline) - TODAY) / DAY) : null);
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmtDate = (s) => { const d = parseDate(s); return d ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}` : "—"; };

  const CUR = { EUR: "€", USD: "$", CHF: "CHF ", GBP: "£" };
  function money(v, { compact = true, currency = "EUR" } = {}) {
    if (v == null || isNaN(v)) return null;
    const sym = CUR[currency] || currency + " ";
    if (!compact) return sym + Math.round(v).toLocaleString("de-AT");
    if (v >= 1e6) return sym + (v / 1e6).toLocaleString("en", { maximumFractionDigits: v >= 1e7 ? 0 : 2 }) + "M";
    if (v >= 1e3) return sym + (v / 1e3).toLocaleString("en", { maximumFractionDigits: v >= 1e5 ? 0 : 1 }) + "k";
    return sym + Math.round(v);
  }
  /** Funding per project when known (cls ""); otherwise the whole call budget (cls "total"),
   *  which must never read as a per-project amount; otherwise "Not stated". */
  function amountText(a) {
    const o = { currency: a?.currency || "EUR" };
    if (a && (a.max_eur != null || a.min_eur != null)) {
      if (a.min_eur != null && a.max_eur != null && a.min_eur < a.max_eur) return { main: `${money(a.min_eur, o)} – ${money(a.max_eur, o)}`, cls: "" };
      if (a.max_eur != null) return { main: `up to ${money(a.max_eur, o)}`, cls: "" };
      return { main: `from ${money(a.min_eur, o)}`, cls: "" };
    }
    if (a?.total_budget_eur != null) return { main: money(a.total_budget_eur, o), cls: "total" };
    return { main: "Not stated", cls: "none" };
  }
  const TOTAL_HINT = "Whole call budget, shared by all funded projects. The amount per project is not stated.";
  /** Per-project amount only: filters and the amount sort never treat a call budget as a project amount. */
  const amountSort = (c) => c.amount?.max_eur ?? c.amount?.min_eur ?? -1;
  const isEstimate = (c) => ["computed", "AI extracted", "extracted from text"].includes(c.amount?.source);
  const amountLabel = (c) => { const a = amountText(c.amount); return (isEstimate(c) && !a.cls ? "≈ " : "") + a.main; };

  const ICON = {
    x: '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M18.3 5.7 12 12l6.3 6.3-1.4 1.4L10.6 13.4 4.3 19.7 2.9 18.3 9.2 12 2.9 5.7l1.4-1.4 6.3 6.3 6.3-6.3 1.4 1.4Z"/></svg>',
    ext: '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M14 3h7v7h-2V6.4l-9.3 9.3-1.4-1.4L17.6 5H14V3ZM5 5h6v2H5v12h12v-6h2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z"/></svg>',
    caret: '<svg class="caret" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="m9 7 5 5-5 5V7Z"/></svg>',
  };

  /** Deadline status as plain text; only the near ones are coloured. */
  function urgency(c) {
    const d = daysLeft(c);
    if (c.status === "watch") return { cls: "", text: "No open call right now" };
    if (c.status === "rolling" && (d == null || d > 60)) return { cls: "", text: "Rolling submission" };
    if (d == null) return { cls: "", text: c.status === "forthcoming" ? "Opens soon" : "No fixed deadline" };
    if (d <= 0) return { cls: "critical", text: "Closes today" };
    if (d <= 14) return { cls: "critical", text: `${d} day${d === 1 ? "" : "s"} left` };
    if (d <= 30) return { cls: "serious", text: `${d} days left` };
    if (d <= 120) return { cls: "", text: `${d} days left` };
    return { cls: "", text: `${Math.round(d / 30)} months left` };
  }
  const noDeadlineLabel = (c) => ({ rolling: "Rolling", watch: "Watch" }[c.status] || "TBA");
  const directOK = (c) => !(c.eligibility || "").startsWith("⚠");

  // ------------------------------------------------------------------ sources: categories → groups
  const CATEGORIES = [
    { key: "at", label: "Austrian agencies", test: (s) => /^(FFG|FWF|OeAD|aws|netidee)\b/.test(s) },
    { key: "reg", label: "Austria & Upper Austria", test: (s) => /^(Austrian foundations|Austrian ministries|Upper Austria|Interreg)/.test(s) },
    { key: "eu", label: "European Union", test: (s) => /^(EU ·|Erasmus\+|EIT|European partnerships)/.test(s) },
    { key: "agg", label: "Aggregators & databases", test: (s) => /^(Open calls ·|Call databases)/.test(s) },
    { key: "int", label: "International", test: () => true },
  ];
  const categoryOf = (s) => CATEGORIES.find((c) => c.test(s));
  const GROUP_ORDER = ["FFG", "FWF", "OeAD", "aws", "netidee", "Austrian ministries", "Austrian foundations", "Upper Austria · regional", "Upper Austria · City", "Interreg",
    "EU · Horizon Europe", "EU · Creative Europe", "Erasmus+", "EU · Erasmus+", "EU · Digital Europe", "EU · CERV", "EIT", "EU · Other", "EU · Cascade", "European partnerships",
    "Open calls · On the Move", "Open calls · S+T+ARTS", "Open calls · EUREKA", "Open calls · Interreg", "Call databases",
    "Games, EdTech", "International foundations", "Multinational"];
  function groupRank(name) {
    const cat = CATEGORIES.indexOf(categoryOf(name));
    const i = GROUP_ORDER.findIndex((p) => name.startsWith(p));
    return cat * 100 + (i === -1 ? 99 : i);
  }
  /** Short label for the source tree, cards and table (full name stays in the tooltip and group heading). */
  const SHORT = [
    [/^FFG/, "FFG"], [/^FWF/, "FWF"], [/^OeAD · Sparkling/, "Sparkling Science"], [/^aws/, "aws"], [/^netidee/, "netidee"],
    [/^Austrian foundations/, "Public funds"], [/^Austrian ministries/, "Ministries & federal"],
    [/^Upper Austria · City of Linz/, "City of Linz"], [/^Upper Austria/, "Upper Austria"],
    [/^European partnerships/, "EU partnerships"], [/^Open calls · On the Move/, "On the Move"], [/^Open calls · S\+T\+ARTS/, "S+T+ARTS"],
    [/^Open calls · EUREKA/, "EUREKA"], [/^Call databases/, "Call databases"],
    [/^Interreg · Bayern/, "Interreg BY–AT"], [/^Interreg · Österreich–Tschechien/, "Interreg AT–CZ"],
    [/^EU · Horizon Europe \(MSCA\)/, "Horizon · MSCA"], [/^EU · Cascade/, "Cascade funding"], [/^EU · CERV/, "CERV"],
    [/^Erasmus\+ · OeAD/, "Erasmus+ (OeAD)"], [/^EU · Erasmus\+/, "Erasmus+ (EU)"], [/^EIT/, "EIT"],
    [/^Games, EdTech/, "Games & EdTech"], [/^International foundations/, "Prizes & foundations"], [/^Multinational/, "Multinational"],
  ];
  function shortName(s) {
    const hit = SHORT.find(([rx]) => rx.test(s));
    return hit ? hit[1] : s.replace(/^EU · /, "");
  }
  const allSources = [...new Set(DATA.calls.map((c) => c.source))].sort((a, b) => groupRank(a) - groupRank(b) || a.localeCompare(b));
  const srcSelected = (s) => !state.sources.size || state.sources.has(s);

  function setSources(list) {
    state.sources = new Set(list);
    if (state.sources.size === allSources.length) state.sources.clear();
  }
  function toggleSource(s) {
    const cur = new Set(state.sources.size ? state.sources : allSources);
    cur.has(s) ? cur.delete(s) : cur.add(s);
    setSources(cur);
  }
  function toggleCategory(key) {
    const members = allSources.filter((s) => categoryOf(s).key === key);
    const cur = new Set(state.sources.size ? state.sources : allSources);
    const allOn = members.every((s) => cur.has(s));
    members.forEach((s) => (allOn ? cur.delete(s) : cur.add(s)));
    setSources(cur);
  }

  // ------------------------------------------------------------------ topics (lab research areas)
  const TOPICS = (DATA.topics || []).filter((t) => t.key);
  const topicShort = Object.fromEntries(TOPICS.map((t) => [t.key, t.short]));
  const topicLabel = Object.fromEntries(TOPICS.map((t) => [t.key, t.label]));
  /** The lab's research areas, with their colours and point-and-line icons.
   *  Each groups one or more of the scraper's topic keys; "themes" are cross-cutting topics without a lab area. */
  const AREAS = [
    { key: "vision", name: "Visual Computing", topics: ["vision"],
      icon: { vb: "0 0 66.81 68.82", c: [[39.3, 4.24], [40.59, 64.58], [4.24, 35.13], [62.57, 28.95]], r: 4.24,
        l: [[39.3, 4.24, 62.57, 28.95], [4.24, 35.13, 39.3, 4.24], [40.59, 64.58, 4.24, 35.13], [4.24, 35.13, 62.57, 28.95], [40.59, 64.58, 62.57, 28.95]] } },
    { key: "web", name: "Intelligent Web Applications", topics: ["ai"],
      icon: { vb: "0 0 57.61 61.35", c: [[44.04, 57.11], [53.38, 4.24], [4.24, 25.07], [35.56, 30.82]], r: 4.24,
        l: [[4.24, 25.07, 35.56, 30.82], [35.56, 30.82, 53.38, 4.24], [44.04, 57.11, 35.56, 30.82]] } },
    { key: "games", name: "Games and Playful Experiences", topics: ["games", "edugames", "installations"],
      icon: { vb: "0 0 46.76 47.68", c: [[23.12, 40.02], [23.12, 7.65], [7.65, 23.24], [39.1, 24.71]], r: 7.65, l: [] } },
    { key: "ui", name: "User Interfaces", topics: ["hci", "xr"],
      icon: { vb: "0 -27.44 63.36 63.36", c: [[59.12, 4.24], [41.38, 4.24], [4.24, 4.24], [22.56, 4.24]], r: 4.24,
        l: [[4.24, 4.24, 59.12, 4.24]] } },
    { key: "tangible", name: "Smart and Tangible", topics: ["tangible"],
      icon: { vb: "0 0 40.06 39.37", c: [[35.82, 4.24], [4.24, 35.13], [4.24, 4.24], [35.82, 35.13]], r: 4.24, dash: true,
        l: [[4.24, 4.24, 35.82, 4.24], [35.82, 4.24, 35.82, 35.13], [35.82, 35.13, 4.24, 35.13], [4.24, 35.13, 4.24, 4.24]] } },
    { key: "dataviz", name: "Data Visualization", topics: ["dataviz"],
      icon: { vb: "0 0 91.51 68.24", c: [[31.54, 19.83], [81.65, 4.24], [7.82, 42.76], [56.1, 33.41]], r: 4.24,
        l: [[1, 67.24, 90.51, 67.24], [56.1, 33.41, 81.65, 4.24], [56.1, 33.41, 31.54, 19.83], [7.82, 42.76, 31.54, 19.83],
          [7.82, 42.76, 7.82, 67.24], [31.54, 19.83, 31.54, 67.24], [56.1, 33.41, 56.1, 67.24], [81.65, 4.24, 81.65, 67.24]] } },
  ];
  const THEMES = ["education", "society", "open"];
  const areaOf = Object.fromEntries(AREAS.flatMap((a) => a.topics.map((t) => [t, a])));
  function iconSVG({ vb, c, r, l, dash }) {
    return `<svg class="area-icon" viewBox="${vb}" aria-hidden="true">`
      + l.map(([x1, y1, x2, y2]) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"${dash ? ' stroke-dasharray="5.4 6.8"' : ""}/>`).join("")
      + c.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${r}"/>`).join("") + "</svg>";
  }
  const topicVar = (t) => (areaOf[t] ? `style="--c: var(--area-${areaOf[t].key})"` : "");
  /** The lab research areas a call fits (coloured, site order), then its cross-cutting themes (grey). */
  function areaTagsHTML(c) {
    const ts = c.topics || [];
    const areas = AREAS.filter((a) => a.topics.some((t) => ts.includes(t))).map((a) => {
      const hit = a.topics.filter((t) => ts.includes(t)).map((t) => topicShort[t] || t).join(", ");
      return `<span class="tag" style="--c: var(--area-${a.key})" title="${esc(hit)}">${esc(a.name)}</span>`;
    });
    const themes = THEMES.filter((t) => ts.includes(t)).map((t) => `<span class="tag tag--neutral" title="${esc(topicLabel[t] || t)}">${esc(topicShort[t] || t)}</span>`);
    return areas.length || themes.length ? `<span class="call__tags">${[...areas, ...themes].join("")}</span>` : "";
  }
  /** Readable label for the selected topics: whole areas by their area name, otherwise the single topics. */
  function topicsLabel() {
    const parts = [], left = new Set(state.topics);
    AREAS.forEach((a) => { if (a.topics.length > 1 && a.topics.every((t) => left.has(t))) { parts.push(a.name); a.topics.forEach((t) => left.delete(t)); } });
    left.forEach((t) => parts.push(topicShort[t] || t));
    return parts.join(" or ");
  }
  function setTopics(set) { state.topics = new Set(set); store.set("topics", [...state.topics]); }

  // ------------------------------------------------------------------ filtering
  function matchesTopics(c) {
    return !state.topics.size || (c.topics || []).some((t) => state.topics.has(t));
  }
  function matchesBase(c, includeLow) {
    if (!includeLow && c.relevance < FIT_MIN) return false;
    if (!state.showWatch && c.status === "watch") return false;
    if (state.directOnly && !directOK(c)) return false;
    if (state.starredOnly && !state.stars.has(c.id)) return false;
    if (state.newOnly && !c.is_new) return false;
    // "time left": hide calls closing sooner than the chosen minimum; rolling / undated calls stay
    if (state.window !== "all") { const d = daysLeft(c); if (d != null && d < +state.window) return false; }
    if (state.minAmount === "known") { if (amountSort(c) < 0) return false; }
    else if (+state.minAmount > 0 && amountSort(c) < +state.minAmount) return false;
    if (state.q) {
      const hay = [c.title, c.summary, c.programme, c.funder, c.source, c.fit_reason, (c.topics || []).map((t) => topicShort[t]).join(" "), (c.keywords || []).join(" "), (c.matched_terms || []).join(" "), c.action_type].join(" ").toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).every((t) => hay.includes(t))) return false;
    }
    return true;
  }
  function filtered({ ignoreSource = false, ignoreTopics = false, includeLow = state.showLow } = {}) {
    return DATA.calls.filter((c) => matchesBase(c, includeLow)
      && (ignoreTopics || matchesTopics(c))
      && (ignoreSource || srcSelected(c.source)));
  }
  const rankNoDate = (c) => (c.deadline ? c.deadline : c.status === "watch" ? "9999-z" : "9999");
  const byDeadline = (a, b) => rankNoDate(a).localeCompare(rankNoDate(b)) || b.relevance - a.relevance;
  const SORTS = {
    deadline: byDeadline,
    fit: (a, b) => b.relevance - a.relevance || byDeadline(a, b),
    newest: (a, b) => (b.first_seen || "").localeCompare(a.first_seen || "") || byDeadline(a, b),
    // per-project amounts first (largest first), then calls with only a total budget, then none
    amount: (a, b) => amountSort(b) - amountSort(a) || (b.amount?.total_budget_eur ?? -1) - (a.amount?.total_budget_eur ?? -1) || byDeadline(a, b),
    title: (a, b) => a.title.localeCompare(b.title, "de", { sensitivity: "base" }),
    source: (a, b) => groupRank(a.source) - groupRank(b.source) || a.source.localeCompare(b.source) || byDeadline(a, b),
  };
  function sorter() {
    const f = SORTS[state.sortBy] || byDeadline;
    return state.sortDir < 0 ? (a, b) => f(b, a) : f;
  }

  // ------------------------------------------------------------------ header
  function renderHeader() {
    if (!DATA.generated_at) return;
    const g = new Date(DATA.generated_at);
    $("#updated").textContent = `Updated ${g.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`;
    $("#updated").title = `Last scraper run: ${g.toLocaleString()} · refreshed automatically every Monday morning`;
  }
  function renderLede() {
    const strong = DATA.calls.filter((c) => c.status !== "watch" && c.relevance >= FIT_MIN).length;
    const fresh = DATA.calls.filter((c) => c.is_new && c.relevance >= FIT_MIN).length;
    $("#lede").innerHTML = `<b>${strong}</b> open and upcoming calls with a strong fit to the lab's research areas, sorted by deadline.`
      + (fresh ? ` <button type="button" class="link" data-new-only>${fresh} new this week</button>` : "");
  }

  // ------------------------------------------------------------------ sidebar: topics + sources
  function renderTopics() {
    const base = filtered({ ignoreTopics: true });
    const count = (keys) => base.filter((c) => (c.topics || []).some((t) => keys.includes(t))).length;
    const pill = (key) => {
      const on = state.topics.has(key), n = count([key]);
      return `<button type="button" class="tpill${on ? " on" : ""}" data-topic="${key}" aria-pressed="${on}" title="${esc(topicLabel[key])}" ${topicVar(key)} ${!n && !on ? "disabled" : ""}>${esc(topicShort[key] || key)}<span class="tpill__n">${n}</span></button>`;
    };
    const areas = AREAS.filter((a) => a.topics.some((t) => topicShort[t])).map((a) => {
      const sel = a.topics.filter((t) => state.topics.has(t)).length, n = count(a.topics);
      // areas that bundle several topics show them as sub-pills once the area is selected, to narrow down
      const subs = a.topics.length > 1 && sel
        ? `<div class="area__subs">${a.topics.filter((t) => topicShort[t]).map(pill).join("")}</div>` : "";
      return `<div class="area${sel ? " on" : ""}" style="--c: var(--area-${a.key})">
        <button type="button" class="area__row" data-area="${a.key}" aria-pressed="${sel ? (sel === a.topics.length ? "true" : "mixed") : "false"}"
          title="${esc(a.topics.map((t) => topicShort[t]).join(" · "))}" ${!n && !sel ? "disabled" : ""}>
          <span class="area__tile">${iconSVG(a.icon)}</span><span class="area__name">${esc(a.name)}</span><span class="tpill__n">${n}</span>
        </button>${subs}
      </div>`;
    }).join("");
    const themes = THEMES.filter((t) => topicShort[t]);
    $("#topicBar").innerHTML = `<div class="areas">${areas}</div>`
      + (themes.length ? `<h4 class="themes__title">Cross-cutting themes</h4><div class="topics">${themes.map(pill).join("")}</div>` : "");
  }

  const openCats = new Set(store.get("openCats", []));
  function renderSourceTree() {
    const counts = {};
    filtered({ ignoreSource: true }).forEach((c) => (counts[c.source] = (counts[c.source] || 0) + 1));
    const visible = allSources.filter((s) => counts[s] || state.sources.has(s));
    $("#sourceTree").innerHTML = CATEGORIES.map((cat) => {
      const members = visible.filter((s) => categoryOf(s) === cat);
      if (!members.length) return "";
      const on = members.filter(srcSelected).length;
      const n = members.reduce((t, s) => t + (counts[s] || 0), 0);
      const open = openCats.has(cat.key);
      return `<div class="tree__cat${open ? " open" : ""}">
        <div class="tree__head">
          <button type="button" class="tree__fold" data-fold="${cat.key}" aria-expanded="${open}" title="${open ? "Hide" : "Show"} sources">${ICON.caret}<span class="sr-only">${esc(cat.label)}</span></button>
          <label><input type="checkbox" data-src-cat="${cat.key}" ${on === members.length ? "checked" : ""} ${on && on < members.length ? 'data-mixed="1"' : ""}>
          <span class="tree__name">${esc(cat.label)}</span></label><span class="tree__n">${n}</span>
        </div>
        <div class="tree__kids">${members.map((s) => `
        <div class="tree__row">
          <label><input type="checkbox" data-src="${esc(s)}" ${srcSelected(s) ? "checked" : ""}>
          <span class="tree__name" title="${esc(s)}">${esc(shortName(s))}</span></label>
          <button type="button" class="tree__only" data-src-only="${esc(s)}" title="Show only this source">only</button>
          <span class="tree__n">${counts[s] || 0}</span>
        </div>`).join("")}</div>
      </div>`;
    }).join("");
    $$('#sourceTree input[data-mixed="1"]').forEach((i) => (i.indeterminate = true));
  }

  // ------------------------------------------------------------------ active filter line
  function activeFilters() {
    const out = [];
    if (state.q) out.push({ k: "q", label: `“${state.q}”` });
    if (state.topics.size) out.push({ k: "topics", label: topicsLabel() });
    if (state.window !== "all") out.push({ k: "window", label: `${$("#window").selectedOptions[0].textContent} left` });
    if (state.minAmount !== "0") out.push({ k: "minAmount", label: $("#minAmount").selectedOptions[0].textContent });
    if (state.sources.size) {
      const names = [...state.sources].map(shortName);
      out.push({ k: "sources", label: names.length <= 2 ? names.join(", ") : `${names.length} sources` });
    }
    if (state.directOnly) out.push({ k: "directOnly", label: "Lab can apply directly" });
    if (state.newOnly) out.push({ k: "newOnly", label: "New this week" });
    if (state.starredOnly) out.push({ k: "starredOnly", label: "Starred" });
    if (!state.showWatch) out.push({ k: "showWatch", label: "Without monitored funders" });
    return out;
  }
  function renderActive(list, low) {
    const calls = list.filter((c) => c.status !== "watch").length, watched = list.length - calls;
    const chips = activeFilters();
    $("#activeBar").innerHTML = `<span class="active__count"><b>${calls}</b> call${calls === 1 ? "" : "s"}${watched ? ` · ${watched} monitored` : ""}`
      + `${low.length && !state.showLow ? ` · ${low.length} lower fit hidden` : ""}</span>`
      + chips.map((f) => `<button type="button" class="fchip" data-clear="${f.k}" title="Remove filter">${esc(f.label)}${ICON.x}</button>`).join("")
      + (chips.length > 1 ? `<button type="button" class="link" data-clear="all">Clear all</button>` : "");
    $("#clearAll").hidden = !chips.length;
    $("#filtBadge").hidden = !chips.length;
    $("#filtBadge").textContent = chips.length;
  }
  function clearFilter(k) {
    if (k === "all") return resetAll();
    if (k === "q") { state.q = ""; $("#q").value = ""; }
    if (k === "topics") setTopics([]);
    if (k === "window") { state.window = "all"; $("#window").value = "all"; }
    if (k === "minAmount") { state.minAmount = "0"; $("#minAmount").value = "0"; }
    if (k === "sources") state.sources.clear();
    if (k === "directOnly") { state.directOnly = false; $("#directOnly").checked = false; }
    if (k === "newOnly") { state.newOnly = false; $("#newOnly").checked = false; }
    if (k === "starredOnly") { state.starredOnly = false; $("#starredOnly").checked = false; }
    if (k === "showWatch") { state.showWatch = true; $("#showWatch").checked = true; }
    render();
  }

  // ------------------------------------------------------------------ cards
  function cardHTML(c) {
    const d = parseDate(c.deadline);
    const u = urgency(c), a = amountText(c.amount);
    const starred = state.stars.has(c.id);
    const prog = /^[A-Za-z0-9]+(-[A-Za-z0-9]+)+$/.test(c.programme || "") ? "" : c.programme;    // EU topic codes are noise on the card
    const src = [shortName(c.source), prog].filter(Boolean).join(" · ");
    const watchNote = c.status === "watch" && c.deadline_note
      ? c.deadline_note.replace(/^No open call found on the funder's page · usual rhythm: /, "Usually: ") : "";
    return `
    <article class="call${c.status === "watch" ? " call--watch" : ""}" data-card="${esc(c.id)}">
      <div class="call__date">
        ${d ? `<span class="mon">${MONTHS[d.getMonth()]}</span><span class="day">${d.getDate()}</span><span class="yr">${d.getFullYear()}</span>`
            : `<span class="nodate">${noDeadlineLabel(c)}</span>`}
      </div>
      <div class="call__main">
        <p class="call__src" title="${esc(c.source)}">${esc(src)}</p>
        <h3 class="call__title"><button type="button" data-open="${esc(c.id)}">${esc(c.title)}</button>${c.is_new ? `<span class="new" title="First found on ${fmtDate(c.first_seen)}">New</span>` : ""}</h3>
        <p class="call__summary">${esc(watchNote || c.summary)}</p>
        <div class="call__foot">
          ${areaTagsHTML(c)}
          <span class="meta${u.cls ? " meta--" + u.cls : ""}">${esc(u.text)}</span>
          ${c.relevance < FIT_MIN ? `<span class="meta" title="Fit score against the lab profile">Lower fit · ${c.relevance}</span>` : ""}
          ${!directOK(c) ? `<span class="meta" title="${esc(c.eligibility)}">Partner role only</span>` : ""}
        </div>
      </div>
      <div class="call__amount" title="${a.cls === "total" ? TOTAL_HINT : c.amount?.source ? "Amount: " + esc(c.amount.source) : ""}">
        <span class="v ${a.cls}">${esc(amountLabel(c))}</span>${a.cls === "total" ? '<span class="l l--total">Total budget · not per project</span>'
          : a.cls !== "none" ? '<span class="l">per project</span>' : ""}
      </div>
      <button class="star" type="button" data-star="${esc(c.id)}" aria-pressed="${starred}" title="${starred ? "Unstar" : "Star"}">${starred ? "★" : "☆"}</button>
    </article>`;
  }

  function renderCards(list) {
    if (!list.length) return emptyHTML();
    const rows = [...list].sort(sorter());
    if (state.sortBy !== "source") return rows.map(cardHTML).join("");
    // sorted by source: show a heading per source
    let last = null, html = "";
    rows.forEach((c) => {
      if (c.source !== last) {
        const n = rows.filter((x) => x.source === c.source).length;
        html += `<h2 class="group-head">${esc(c.source)}<span>${n}</span></h2>`;
        last = c.source;
      }
      html += cardHTML(c);
    });
    return html;
  }

  // ------------------------------------------------------------------ table
  function renderTable(list) {
    if (!list.length) return emptyHTML();
    const k = state.sortBy, dir = state.sortDir;
    const rows = [...list].sort(sorter());
    const th = (key, label, cls = "") => `<th data-sort="${key}" class="${cls}" ${k === key ? `aria-sort="${dir > 0 ? "ascending" : "descending"}"` : ""}>${label}${k === key ? (dir > 0 ? " ↓" : " ↑") : ""}</th>`;
    return `<div class="table-wrap"><table class="calls">
      <thead><tr>${th("deadline", "Deadline")}${th("title", "Call")}${th("source", "Source")}${th("amount", "Per project", "num")}${th("fit", "Fit", "num")}</tr></thead>
      <tbody>${rows.map((c) => {
        const u = urgency(c);
        return `<tr data-card="${esc(c.id)}">
          <td class="date">${c.deadline ? fmtDate(c.deadline) : noDeadlineLabel(c)}${u.cls ? `<div class="small meta--${u.cls}">${esc(u.text)}</div>` : ""}</td>
          <td><span class="t">${esc(c.title)}</span>${c.is_new ? '<span class="new">New</span>' : ""}</td>
          <td class="small">${esc(shortName(c.source))}</td>
          <td class="num">${esc(amountLabel(c))}${amountText(c.amount).cls === "total" ? `<div><span class="total-badge" title="${TOTAL_HINT}">total budget</span></div>` : ""}</td>
          <td class="num">${c.relevance}</td>
        </tr>`;
      }).join("")}</tbody></table></div>`;
  }

  function emptyHTML(nLow = 0) {
    return `<div class="empty"><p><b>No ${nLow ? "strong-fit " : ""}calls match these filters.</b></p><p class="small">${nLow ? "Lower-fit calls are listed below, or try" : "Try"} less time left or fewer filters.</p><button class="btn" type="button" data-clear="all">Reset filters</button></div>`;
  }
  /** Divider at the end of the list that reveals / hides the calls under FIT_MIN. */
  function lowToggleHTML(n) {
    return `<div class="lowfit">
      <button type="button" class="lowfit__btn" data-low aria-expanded="${state.showLow}">${state.showLow ? "Hide" : "Show"} ${n} lower-fit call${n === 1 ? "" : "s"}</button>
      <span class="small muted">fit score below ${FIT_MIN}</span>
    </div>`;
  }

  // ------------------------------------------------------------------ drawer
  let opener = null;
  function openDrawer(id) {
    const c = DATA.calls.find((x) => x.id === id);
    if (!c) return;
    const u = urgency(c);
    $("#drawerTitle").textContent = c.title;
    const fact = (k, v, n = "", cls = "") => (v ? `<div class="fact ${cls}"><div class="k">${k}</div><div class="v${cls.includes("money") ? " big" : ""}">${v}</div>${n ? `<div class="n">${n}</div>` : ""}</div>` : "");
    const amt = amountText(c.amount), isTotal = amt.cls === "total";
    const amtNote = [isTotal && "Not per project: the budget for the whole call, shared by all funded projects",
      c.amount?.funding_rate && "Funding rate " + esc(c.amount.funding_rate),
      !isTotal && c.amount?.total_budget_eur && "call budget " + money(c.amount.total_budget_eur),
      c.amount?.expected_grants && `~${c.amount.expected_grants} grants`, c.amount?.note && esc(c.amount.note)].filter(Boolean).join(" · ");
    const deadlineNote = [u.text, c.deadlines?.length > 1 ? "also " + c.deadlines.filter((x) => x !== c.deadline).map(fmtDate).join(", ") : ""].filter(Boolean).join(" · ");
    $("#drawerBody").innerHTML = `
      <p class="drawer__src">${esc([c.funder, c.programme].filter(Boolean).join(" · "))}</p>
      <div class="facts">
        ${fact(isTotal ? "Total call budget" : "Funding per project", esc(amountLabel(c)), amtNote, isTotal ? "money total" : "money")}
        ${fact("Deadline", c.deadline ? fmtDate(c.deadline) : noDeadlineLabel(c), esc(deadlineNote))}
        ${fact("Opens", c.opening_date ? fmtDate(c.opening_date) : "")}
        ${fact("Fit score", `${c.relevance} / 100`, c.relevance < FIT_MIN ? `Below the ${FIT_MIN} cutoff` : "Against the lab profile")}
      </div>
      ${c.deadline_note ? `<p class="small muted">${esc(c.deadline_note)}</p>` : ""}
      <h3>Summary</h3><p>${esc(c.summary)}</p>
      ${c.fit_reason ? `<h3>Why it fits the lab</h3><p>${esc(c.fit_reason)}</p>` : ""}
      ${c.eligibility ? `<h3>Who can apply</h3><p>${esc(c.eligibility)}</p>` : ""}
      ${c.topics?.length ? `<h3>Research areas</h3>${areaTagsHTML(c)}<p class="small muted" style="margin-top:8px">Matched topics: ${esc(c.topics.map((t) => topicShort[t] || t).join(", "))}</p>` : ""}
      <p class="drawer__cta"><a class="btn" href="${esc(c.url)}" target="_blank" rel="noopener">Open official call page ${ICON.ext}</a></p>
      ${c.excerpt ? `<details class="more"><summary>Call text (excerpt)</summary><div class="excerpt">${esc(c.excerpt)}</div>
        ${c.excerpt_credit ? `<p class="small muted" style="margin-top:6px">Source: <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.funder)}</a> · ${esc(c.excerpt_credit)}</p>` : ""}</details>` : ""}
      ${c.action_type ? `<p class="small muted" style="margin-top:10px">Type of action: ${esc(c.action_type)}</p>` : ""}`;
    $("#scrim").hidden = false;
    $("#drawer").hidden = false;
    $("#drawerClose").focus();
    history.replaceState(null, "", "#call=" + encodeURIComponent(id));
  }
  function closeDrawer() {
    $("#drawer").hidden = true;
    if (!document.body.classList.contains("filters-open")) $("#scrim").hidden = true;
    history.replaceState(null, "", location.pathname + location.search);
    if (opener && document.body.contains(opener)) opener.focus();
  }

  // ------------------------------------------------------------------ CSV
  function exportCSV() {
    const list = filtered().sort(byDeadline);
    const cols = [["Deadline", (c) => c.deadline || c.status], ["Title", (c) => c.title], ["Source", (c) => c.source], ["Funder", (c) => c.funder],
      ["Programme", (c) => c.programme], ["Min per project", (c) => c.amount?.min_eur ?? ""], ["Max per project", (c) => c.amount?.max_eur ?? ""],
      ["Currency", (c) => c.amount?.currency || "EUR"], ["Call budget", (c) => c.amount?.total_budget_eur ?? ""], ["Amount source", (c) => c.amount?.source],
      ["Fit score", (c) => c.relevance], ["Topics", (c) => (c.topics || []).map((t) => topicShort[t] || t).join(", ")], ["Summary", (c) => c.summary], ["URL", (c) => c.url]];
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [cols.map((c) => q(c[0])).join(";"), ...list.map((c) => cols.map(([, fn]) => q(fn(c))).join(";"))].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = `funding-calls-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ------------------------------------------------------------------ main render
  function render() {
    const all = filtered({ includeLow: true });
    const main = all.filter((c) => c.relevance >= FIT_MIN), low = all.filter((c) => c.relevance < FIT_MIN);
    renderTopics();
    renderSourceTree();
    renderActive(main, low);
    const body = (l) => (state.view === "table" ? renderTable(l) : renderCards(l));
    $("#results").innerHTML = (main.length ? body(main) : emptyHTML(low.length))
      + (low.length ? lowToggleHTML(low.length) + (state.showLow ? body(low) : "") : "");
    $("#sortBy").value = state.sortBy;
    $$(".seg [data-view]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.view === state.view)));
  }

  function resetAll() {
    Object.assign(state, { q: "", showLow: false, window: "all", minAmount: "0", showWatch: true, directOnly: false, starredOnly: false, newOnly: false });
    state.sources.clear();
    setTopics([]);
    $("#q").value = ""; $("#window").value = "all"; $("#minAmount").value = "0";
    $("#directOnly").checked = false; $("#starredOnly").checked = false; $("#newOnly").checked = false; $("#showWatch").checked = true;
    render();
  }

  // ------------------------------------------------------------------ filter sheet (small screens)
  function setFilters(open) {
    document.body.classList.toggle("filters-open", open);
    $("#filtersBtn").setAttribute("aria-expanded", String(open));
    $("#scrim").hidden = !open && $("#drawer").hidden;
  }
  $("#filtersBtn").addEventListener("click", () => setFilters(true));
  $("#filtersClose").addEventListener("click", () => setFilters(false));

  // ------------------------------------------------------------------ events
  let qTimer;
  $("#q").addEventListener("input", (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 150); });
  $("#window").addEventListener("change", (e) => { state.window = e.target.value; render(); });
  $("#minAmount").addEventListener("change", (e) => { state.minAmount = e.target.value; render(); });
  $("#directOnly").addEventListener("change", (e) => { state.directOnly = e.target.checked; render(); });
  $("#starredOnly").addEventListener("change", (e) => { state.starredOnly = e.target.checked; render(); });
  $("#newOnly").addEventListener("change", (e) => { state.newOnly = e.target.checked; render(); });
  $("#showWatch").addEventListener("change", (e) => { state.showWatch = e.target.checked; render(); });
  $("#sortBy").addEventListener("change", (e) => { state.sortBy = e.target.value; state.sortDir = 1; store.set("sort", state.sortBy); render(); });
  $$(".seg [data-view]").forEach((b) => b.addEventListener("click", () => { state.view = b.dataset.view; store.set("view", state.view); render(); }));
  $("#exportBtn").addEventListener("click", exportCSV);

  // source tree (delegated)
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.matches("input[data-src]")) { toggleSource(t.dataset.src); render(); }
    else if (t.matches("input[data-src-cat]")) { toggleCategory(t.dataset.srcCat); render(); }
  });

  document.addEventListener("click", (e) => {
    const fold = e.target.closest("[data-fold]");
    if (fold) {
      const k = fold.dataset.fold;
      openCats.has(k) ? openCats.delete(k) : openCats.add(k);
      store.set("openCats", [...openCats]);
      renderSourceTree(); return;
    }
    const ar = e.target.closest("[data-area]");
    if (ar) {
      const a = AREAS.find((x) => x.key === ar.dataset.area), only = e.altKey || e.metaKey;   // Alt/⌘-click = only this area
      const next = new Set(only ? [] : state.topics), any = a.topics.some((t) => state.topics.has(t));
      a.topics.forEach((t) => (any && !only ? next.delete(t) : next.add(t)));
      setTopics(next); render(); return;
    }
    const tp = e.target.closest("[data-topic]");
    if (tp) {
      const t = tp.dataset.topic, next = new Set(state.topics);
      if (e.altKey || e.metaKey) { setTopics(next.has(t) && next.size === 1 ? [] : [t]); }   // Alt/⌘-click = only this topic
      else { next.has(t) ? next.delete(t) : next.add(t); setTopics(next); }
      render(); return;
    }
    const only = e.target.closest("[data-src-only]");
    if (only) { e.preventDefault(); setSources([only.dataset.srcOnly]); render(); return; }
    const clr = e.target.closest("[data-clear]");
    if (clr) { clearFilter(clr.dataset.clear); return; }
    const star = e.target.closest("[data-star]");
    if (star) {
      const id = star.dataset.star;
      state.stars.has(id) ? state.stars.delete(id) : state.stars.add(id);
      store.set("stars", [...state.stars]);
      if (state.starredOnly) render();
      else { star.setAttribute("aria-pressed", String(state.stars.has(id))); star.textContent = state.stars.has(id) ? "★" : "☆"; }
      return;
    }
    const th = e.target.closest("th[data-sort]");
    if (th) {
      const key = th.dataset.sort;
      if (state.sortBy === key) state.sortDir = -state.sortDir;
      else { state.sortBy = key; state.sortDir = 1; store.set("sort", key); }
      render(); return;
    }
    if (e.target.closest("[data-low]")) {
      state.showLow = !state.showLow; render();
      $("[data-low]")?.scrollIntoView({ block: "center" });   // keep the button where the eye is
      return;
    }
    if (e.target.closest("[data-new-only]")) { state.newOnly = true; $("#newOnly").checked = true; render(); return; }
    if (e.target.closest("a")) return;                     // links keep default
    const card = e.target.closest("[data-card]");          // whole card / table row opens the details
    if (card && !window.getSelection().toString()) { opener = card.querySelector("[data-open]") || card; openDrawer(card.dataset.card); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { if (!$("#drawer").hidden) closeDrawer(); else setFilters(false); }
    if (e.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) { e.preventDefault(); $("#q").focus(); }
  });
  $("#drawerClose").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", () => { if (!$("#drawer").hidden) closeDrawer(); setFilters(false); });

  // URL options: ?view=table  ?sort=…  ?topic=…  ?q=…  ?source=<prefix> (repeatable)  #call=<id>
  const params = new URLSearchParams(location.search);
  if (["table", "cards", "list"].includes(params.get("view"))) state.view = params.get("view") === "table" ? "table" : "cards";
  if (SORTS[params.get("sort")]) state.sortBy = params.get("sort");
  if (params.getAll("topic").length) setTopics(params.getAll("topic").filter((t) => topicShort[t]));
  if (params.get("q")) { state.q = params.get("q"); $("#q").value = state.q; }
  const srcParams = params.getAll("source");
  if (srcParams.length) setSources(allSources.filter((x) => srcParams.some((p) => x.startsWith(p))));

  renderHeader();
  renderLede();
  render();
  if (location.hash.startsWith("#call=")) openDrawer(decodeURIComponent(location.hash.slice(6)));
})();
