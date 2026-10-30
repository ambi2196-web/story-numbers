# Deploying the public demo (free)

The public app runs on **Streamlit Community Cloud** with the **Gemini free tier**: the Claude CLI only works on your own computer.

## 1. Put the code on GitHub
1. Create a new **public** repository on GitHub (for example `story-numbers`), with no README.
2. In this folder:
   ```bash
   git remote add origin https://github.com/<you>/story-numbers.git
   git push -u origin main
   ```
   `.env` (your keys), `data/cache/` and `data/game.sqlite` are in `.gitignore` and stay on your computer.

## 2. Create the app
1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app → Deploy a public app from GitHub**.
3. Repository: `<you>/story-numbers`. Branch: `main`. Main file path: `app/ui/streamlit_app.py`.
4. **Advanced settings:**
   - Python version **3.12**.
   - **Secrets:**
     ```toml
     LLM_PROVIDER = "gemini"
     GEMINI_API_KEY = "your-free-key-from-aistudio.google.com"
     SEC_USER_AGENT = "StoryNumbers your-email@example.com"
     ```
     Streamlit passes these to the app as environment variables. They are never in git.
5. Click **Deploy**. The first build takes about 3–5 minutes.

## 3. Check it (5 minutes)
- [ ] Search "Maruti": suggestions appear, then 5 years of financials.
- [ ] The business profile appears straight away. Featured companies ship with it, so it costs no AI call.
- [ ] "Tell your story" with "Maruti takes 70% of India's car market" gives drivers, a scorecard and points.
- [ ] Set a target of 3× in 3 years and find stories.
- [ ] Download the Excel file and open it.
- [ ] Sidebar → 🔑: paste a second Gemini key and confirm "AI in use: gemini (your key)".

## What to know
- **Free AI quota:** one free Gemini key allows roughly a few hundred AI calls a day across the model chain in `GEMINI_MODEL`. When it runs out, visitors see a friendly "come back tomorrow, or add your own key" message. Valuations, Excel files, requirements and scorecards keep working without AI.
- **Leaderboard and saved scenarios** live in `data/game.sqlite` on the server, so they reset when Streamlit restarts the app (after an update, or after days without visitors). That is fine for a demo; a hosted database would be needed to keep them.
- **Featured companies:** rebuild their profiles each quarter (`python -m app.featured build --refresh`), then commit `data/featured/`.
- **NSE company list:** NSE often blocks servers outside India, so the app falls back to `data/nse_equity_seed.csv`. Refresh it now and then by copying `data/cache/nse_equity.csv` over it.
- **Alternative host:** Hugging Face Spaces (Streamlit template) works the same way. Set the same three values as Space secrets.
