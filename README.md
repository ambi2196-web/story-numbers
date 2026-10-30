# Story ⇄ Numbers: a Damodaran-style valuation game

Type a company, tell a story ("Maruti takes 70% of India's car market"), and see what it is worth. Or set a target ("3× in 3 years") and see what has to be true. The plan is in [ROADMAP.md](ROADMAP.md).

## Setup (Windows)

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
copy .env.example .env
```

### AI backends: both are supported
| Use | Backend | One-time setup | `.env` |
|---|---|---|---|
| Personal, local | Claude Code CLI on your Claude Pro plan | Run `claude auth login` in a normal terminal | `LLM_PROVIDER=claude_cli` |
| Public demo | Gemini free tier | Get a free key at https://aistudio.google.com/apikey | `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...` |

`LLM_PROVIDER=auto` uses Claude when the CLI is installed and Gemini otherwise.

Smoke test:
```bash
.venv/Scripts/python -m app.llm --provider claude_cli --json
.venv/Scripts/python -m app.llm --provider gemini --json
```

### Run the app
```bash
.venv/Scripts/python -m streamlit run app/ui/streamlit_app.py
```
Or from the command line (writes `output/<TICKER>_<date>.xlsx`):
```bash
.venv/Scripts/python -m app.collect "Maruti Suzuki"
```

### Tell your story (Mode A)
After the status-quo valuation, type a story ("Maruti takes 70% of India's car market and 80% of its cars are EVs"). The AI turns it into drivers (market size and growth, share, revenue per unit, margin, capital intensity), tagging each as *your story* or *AI inferred*. Revenue is built as units sold × price, the same DCF values it, and a **story vs reality** scorecard grades each driver against the company's five years and its Damodaran industry. Edit any driver and it recomputes; the Excel file gains a *Your story* sheet whose units × price path drives the DCF with live formulas.

### Set a target (Mode B)
Enter a target ("3× in 3 years", a share price or a market cap). If the market prices the company at fair value by then, value must grow into the target at the cost of equity, so the app works out the value needed today, then:
- **one driver at a time:** the growth, margin, capital efficiency or long-run return on capital that alone would get there, in plain terms (e.g. "revenue 8.6× today's by year 5");
- **stories that get there:** the AI writes 2–3 genuinely different routes (e.g. premium SUVs, cost leadership, EV exports). The engine pushes each route's main lever until the story is worth exactly the target, then grades it on Damodaran's 3P test (any red flag = possible, no red flags = plausible, at most one stretch = probable; "out of reach" if no value of the lever gets there).

Any route can be opened in *Tell your story* to edit it. The Excel file gains a *Target* sheet.

### Company data (all free)
| Source | Used for |
|---|---|
| NSE equity list | Search suggestions with NSE's official names (refreshed weekly) |
| Yahoo Finance | Prices, profile, balance-sheet detail, non-Indian search |
| Screener.in | Indian companies: 5+ years of headline financials in ₹ crore |
| SEC EDGAR | US companies: 10-K figures for the 5th year. Set `SEC_USER_AGENT` in `.env` to include your contact email, as SEC asks |

### Industry data
Damodaran's datasets are already parsed into `data/damodaran/parsed/`. Refresh them each January:
```bash
.venv/Scripts/python -m app.data.damodaran refresh
```

### Tests
```bash
.venv/Scripts/python -m pytest -q
```

*Educational tool, not investment advice.*
