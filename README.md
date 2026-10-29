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
