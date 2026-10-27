# Story ⇄ Numbers — A Damodaran-Style Valuation Game

## 1. Product vision

Type any company (real or fictional). In seconds the system:

1. Collects up to 5 years of financials, puts them in an Excel workbook, and explains the business (segments, what drives revenue).
2. Shows the **current story the market is pricing in**: "At ₹X/share, the market assumes Y% growth and Z% margins."
3. Lets the player choose one of two modes:

| Mode | Player gives | System returns |
|---|---|---|
| **A. Story → Numbers** | A narrative: *"Maruti dominates India, takes 70% of the addressable market, 80% of its cars are EVs, mostly entry-level for first-time buyers."* | Value drivers (units, price per car, revenue, margin, reinvestment), a DCF value per share, and a plausibility check against industry benchmarks. |
| **B. Numbers → Story** | A target: *"Maruti's share price triples in 3 years."* | What has to be true: cars sold, market share needed, which untapped segment it has to win, margin and capital efficiency required, and whether that is plausible. |

This follows Damodaran's core idea: **every valuation is a story told in numbers, and every story needs to pass the 3P test (Possible → Plausible → Probable).**

---

## 2. Key design principle: the LLM tells stories, the code does the math

| Layer | Who does it | Why |
|---|---|---|
| Fetching and cleaning financials | Python (free data sources) | Deterministic and auditable |
| DCF / reverse-DCF math | Python valuation engine | LLMs make arithmetic mistakes, so they never compute a value |
| Story → structured assumptions (JSON) | LLM | Language understanding |
| Assumptions → narrative | LLM | Writing |
| Plausibility checks | Python rules + Damodaran industry data, explained by the LLM | Grounded in real benchmarks |

The LLM always returns **structured JSON** (for example `{"tam_units_2035": 6.5e6, "market_share": 0.70, "avg_price": 750000, ...}`). The engine computes the result, and the LLM then explains it. This keeps results consistent and good even on free models.

---

## 3. Zero-cost tech stack

### 3.1 Financial data (free)

| Source | Use | Notes |
|---|---|---|
| **yfinance** (Yahoo Finance) | Price, shares, market cap, about 4 years of annual P&L, balance sheet and cash flow; works for NSE (`MARUTI.NS`) and US tickers | Primary source for the MVP. Unofficial, so cache the results. |
| **Screener.in** (public company page) | 10+ years for Indian companies, segment hints, annual report links | Fallback or supplement for India. Scrape politely, cache, and use for personal/educational purposes only. |
| **SEC EDGAR XBRL API** (`data.sec.gov`) | Official US filings, free, no key | For US companies |
| **Damodaran's datasets** (pages.stern.nyu.edu/~adamodar) | Industry margins, sales-to-capital, betas, cost of capital, equity risk premium, country risk premium (India) | The source of "industry standards". Download once a year as Excel and store locally. |
| **Annual report PDFs / company website** | Segment data and unit volumes (for example cars sold) | Pulled on demand and summarised by the LLM |

### 3.2 LLM options (no paid API)

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Claude via your Pro subscription (Claude Code headless: `claude -p ... --output-format json`)** | The backend runs the Claude Code CLI as a subprocess | Best quality and uses your existing plan | Only works **locally on your machine** with your login, and is subject to Pro usage limits. Not suitable for a public multi-user site. |
| **B. Google Gemini API, free tier** | Free API key from Google AI Studio | Real API with decent free quota, strong JSON output, can be deployed | Rate limits; free-tier data may be used by Google |
| **C. Groq / OpenRouter free models** (Llama, Qwen, DeepSeek) | Free API keys | Fast, deployable | Quality varies |

**Decision (confirmed):** one `LLMProvider` interface with two backends, both kept working at all times:

| Mode | Backend | Where it runs | Set with |
|---|---|---|---|
| **Personal / local** | Claude Code CLI on your Pro plan | Your laptop | `LLM_PROVIDER=claude_cli` |
| **Public / LinkedIn** | Gemini free-tier API | Free cloud host | `LLM_PROVIDER=gemini` |

`LLM_PROVIDER=auto` picks Claude when the CLI is installed and Gemini otherwise. Every feature is tested on **both** providers before it counts as done.

### 3.2.1 LinkedIn launch constraints (built in from day one)
A LinkedIn post can send hundreds of visitors in a day, and one free Gemini key has a daily request cap. To keep the public app working:
- **Cache everything.** A company profile or valuation that has already been generated is served from cache and costs no AI call.
- **Featured companies, pre-built.** Maruti, Tata Motors, Zomato, Apple and similar are generated ahead of time, so the first click is instant and free.
- **Bring your own key (optional).** Visitors can paste their own free Gemini key. It is kept only for their browser session and never stored.
- **Graceful limit.** When the daily quota runs out, show a friendly "come back tomorrow / add your key" message instead of an error.
- **Never expose your key.** Store it as a host secret, never in git.
- **Showcase material:** a public GitHub repo with a clear README, architecture diagram, a 60-second screen recording and one worked example (the Maruti story) for the post.

### 3.3 App stack

- **Backend:** Python + FastAPI (valuation engine, data fetchers, LLM calls)
- **Frontend:** Streamlit for the MVP (fastest path to the search bar → results → story box flow). Move to a Next.js "game" UI in Phase 6 if you want animations and scoring.
- **Excel:** `openpyxl`, writing **live formulas** (not just values) so the user can open the sheet and change assumptions like a real Damodaran spreadsheet
- **Storage:** SQLite for the cache of fetched financials, saved scenarios and the leaderboard
- **Cost:** ₹0

---

## 4. System architecture

```
 ┌──────────────┐
 │  Search bar  │  "Maruti Suzuki" / "My fictional EV startup"
 └──────┬───────┘
        ▼
 ┌──────────────────┐   real    ┌────────────────────────────┐
 │ Company resolver │──────────▶│ Data collector              │ yfinance → Screener → EDGAR
 │ (name → ticker)  │           │ 5Y P&L, BS, CF, price, shares│ + cache (SQLite)
 └──────┬───────────┘           └──────────────┬─────────────┘
        │ fictional                            ▼
        ▼                        ┌────────────────────────────┐
 ┌──────────────────┐            │ Normaliser                  │ EBIT, tax rate, reinvestment,
 │ Fictional builder│──────────▶ │ (standard financial schema) │ invested capital, ROIC, net debt
 │ (industry averages│           └──────────────┬─────────────┘
 │  + user inputs)  │                           ▼
 └──────────────────┘            ┌────────────────────────────┐
                                 │ Business profiler (LLM)     │ segments, revenue drivers,
                                 │                             │ "current market-implied story"
                                 └──────────────┬─────────────┘
                                                ▼
                        ┌───────────── Choose mode ─────────────┐
                        ▼                                       ▼
          ┌──────────────────────────┐          ┌──────────────────────────────┐
          │ A. Story → Numbers        │          │ B. Numbers → Story            │
          │ LLM: story → driver JSON  │          │ Solver: target price → needed │
          │ Engine: DCF               │          │ revenue/margin/reinvestment   │
          │ LLM: explain + caveats    │          │ LLM: narrate "what must be    │
          └────────────┬─────────────┘          │ true" (units, segments)        │
                       │                        └──────────────┬───────────────┘
                       ▼                                       ▼
                 ┌──────────────────────────────────────────────────┐
                 │ Plausibility engine (3P test vs Damodaran data)   │
                 │ Excel export · Scenario save · Score / leaderboard│
                 └──────────────────────────────────────────────────┘
```

---

## 5. The valuation engine (Damodaran FCFF model)

These are the inputs a story has to set, the same ones as in Damodaran's "Ginzu" spreadsheet:

1. **Revenue growth**, years 1–5 and 6–10, or alternatively **TAM × market share × price** (better for story mode)
2. **Target operating margin** and the year it is reached
3. **Sales-to-capital ratio** (reinvestment efficiency)
4. **Cost of capital** (risk-free rate + beta × ERP + country risk), from Damodaran's data
5. **Terminal growth** (≤ risk-free rate) and **terminal ROIC**
6. **Probability of failure** (for young or fictional companies)

Calculation: FCFF = EBIT(1−t) − reinvestment → discount at WACC → add terminal value → + cash − debt − minority interests → ÷ shares = **value per share**, compared with the market price.

**Reverse mode** uses the same engine run backwards. A numeric solver (`scipy.optimize.brentq`) finds the revenue, margin or market share needed to hit the target price. Each driver is solved on its own, then in combination.

**Plausibility rules** (examples):
- Market share above roughly 60% in a competitive industry → red flag
- Margin above the industry's 90th percentile (Damodaran data) → amber
- Implied revenue above the TAM → impossible
- Sales-to-capital far outside the industry range → amber
- Terminal growth above the risk-free rate → impossible

---

## 6. Phase-wise implementation plan

### Phase 0: Foundations (Week 1)
- Project structure, virtual environment, git repo, config (`.env` for LLM provider choice)
- Download and parse Damodaran's datasets (India and global: margins, betas, cost of capital, sales/capital, ERP and CRP)
- Build the `LLMProvider` abstraction (Claude CLI + Gemini) with a "return JSON matching this schema" helper
- **Exit criteria:** `python -m app.llm "hello"` works on both providers, and the Damodaran tables load into pandas

### Phase 1: Data collector + Excel (Weeks 2–3)
- Company resolver: name → ticker (yfinance search + LLM fallback for ambiguous names such as "Maruti" → `MARUTI.NS`)
- Fetch 5 years of P&L, balance sheet, cash flow, price, shares and market cap. Fill gaps from Screener for Indian companies.
- Normalise to a standard schema and compute EBIT margin, effective tax rate, reinvestment, invested capital, ROIC and sales-to-capital
- Excel export: sheets for `Raw Financials`, `Normalised`, `Ratios` and `Industry Benchmarks`
- SQLite cache (do not refetch within 24 hours)
- **Exit criteria:** typing "Maruti Suzuki" gives a correct 5-year Excel file in under 10 seconds. Spot-check it against the annual report.

### Phase 2: Valuation engine (Weeks 3–4)
- Pure-Python FCFF DCF with the inputs from section 5
- Unit tests: reproduce one of Damodaran's published valuations within ±2%
- Excel export of the DCF with **live formulas**
- Reverse-DCF solver: "what growth or margin does the current price imply?"
- **Exit criteria:** the engine matches a reference valuation, and the market-implied assumptions for Maruti look sensible

### Phase 3: Business profile and "current story" (Week 5)
- LLM summarises the lines of business, revenue mix, key unit drivers (cars sold, average price per car) and competitive position, using data passed in plus the annual report or website
- "The market's story today": convert the reverse-DCF output into plain language
- Streamlit MVP: search bar → loading → financials table + business profile + current story + Excel download
- **Exit criteria:** an end-to-end demo for 3 companies (Maruti, Tata Motors, one US company) and 1 fictional company

### Phase 4: Mode A, Story → Numbers (Weeks 6–7)
- Story input box plus guided prompts ("market size? share? pricing? margins?")
- LLM turns the story into a driver JSON (TAM, share, mix such as 80% EV, average price, margin path, capex intensity), with each assumption tagged as *stated by user* or *inferred*
- Engine values it, and the plausibility engine scores each driver against the industry
- Output: units sold per year, revenue, margins, value per share vs current price, a "story vs reality" scorecard, and an updated Excel file
- Let the user tweak any number and recompute instantly
- **Exit criteria:** the Maruti "70% share, 80% EV" story produces coherent numbers and the right red flags

### Phase 5: Mode B, Numbers → Story (Weeks 8–9)
- Input: target price, multiple or market cap, plus a time horizon (for example 3× in 3 years)
- Solver: required revenue, margin and reinvestment, translated into **units to sell, market share, and segment mix**
- LLM: builds 2–3 alternative stories that reach the target (for example "win the EV entry segment", "export push", "premium SUV shift") and ranks them on the 3P test
- **Exit criteria:** "Maruti 3× in 3 years" gives specific, checkable requirements and an honest plausibility verdict

### Phase 6: Game layer (Weeks 10–11)
- Scenario saving and side-by-side comparison (bull, base, bear)
- **Plausibility meter / score:** points for stories that are bold but stay within limits
- Leaderboard and challenges ("Find a story where Paytm is worth ₹2,000", "Value a fictional quick-commerce startup")
- Optional move to a Next.js frontend with animations
- **Exit criteria:** a complete play loop for a friend who has never seen the app

### Phase 7: Hardening and sharing (Week 12)
- Error handling (missing data, delisted tickers, odd fiscal years), rate-limit back-off, caching
- Prompt evaluation set: 20 stories with expected driver ranges, checked against each LLM provider
- Deployment: Streamlit Community Cloud or Hugging Face Spaces (free) using **Gemini free tier**, because the Claude CLI cannot run there
- Pre-generate featured companies, add the bring-your-own-key box and the quota-exhausted message (section 3.2.1)
- Disclaimer: educational tool, not investment advice
- LinkedIn launch kit: README with screenshots, architecture diagram, 60-second demo video, and a post built around one story (for example "What has to be true for Maruti to triple?")

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| yfinance breaks or limits requests | Cache in SQLite, Screener/EDGAR fallback, manual CSV upload as a last resort |
| Unit data (cars sold) is not in financial statements | LLM pulls it from the annual report or investor presentation. The user can edit it. Show the source. |
| LLM hallucinates numbers | LLM only produces assumptions, which are always shown, editable and checked against benchmarks. All math is done in code. |
| Free LLM quotas | Short prompts, cached profiles, Claude CLI used locally |
| Claude Pro cannot power a public site | Use Gemini or Groq for anything deployed |
| Scraping terms of service | Personal and educational use, polite rate limits, prefer official or free APIs |

---

## 8. Proposed folder structure

```
Automatic Valuation/
├── app/
│   ├── data/          # resolver, yfinance, screener, edgar, damodaran loaders, cache
│   ├── engine/        # dcf.py, reverse_dcf.py, plausibility.py
│   ├── llm/           # provider.py (claude_cli, gemini), prompts/, schemas.py
│   ├── story/         # story_to_numbers.py, numbers_to_story.py, profiler.py
│   ├── excel/         # workbook builder with live formulas
│   └── ui/            # streamlit_app.py (later: Next.js)
├── data/damodaran/    # downloaded industry datasets
├── tests/
└── ROADMAP.md
```
