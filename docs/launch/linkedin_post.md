# LinkedIn post (draft)

**Attach:** the 60-second screen recording (see `demo_script.md`), or as a carousel `docs/screenshots/6-target-3x.jpg`, `5-scorecard.jpg` and `4-units-and-value.jpg`.
**Before posting:** replace the two links, and re-run the numbers on the day, because the price moves.

---

What has to be true for Maruti Suzuki to triple in 3 years?

I built a small valuation game to find out. It's based on Aswath Damodaran's idea that every valuation is a story told in numbers.

Today Maruti trades at ₹11,397. If nothing about the business changes, a standard DCF puts it at about ₹6,756.

To triple by 2029, it would need to be worth about ₹22,800 today. That's 3.4× the status quo. One lever alone gets there only if Maruti:
→ grows revenue 54% a year for five years (8.6× today's revenue), or
→ earns a 33% operating margin (Indian carmakers average about 10%).

I asked the AI for stories that could get there, and had the engine grade each one:
🟠 Cost leadership: needs a 38% margin. Possible, not plausible.
🟠 Premium SUVs: needs revenue per car to rise 35% a year. Possible.
🔴 EVs plus exports: out of reach, even at a 95% market share.

So the stock can triple, but only if Maruti does something no carmaker has done. That's the point of the exercise: the story makes the numbers honest, and the numbers keep the story in check.

What the tool does:
• Search any listed company and get 5 years of financials, a business profile and a live-formula Excel DCF
• Tell a story ("Maruti takes 70% of India's car market, 80% EVs") and see cars sold, margins, capital needs and value per share, plus a story-vs-reality scorecard
• Set a target and see what has to be true
• Play: points for stories that are bold but plausible, challenges ("Make Paytm worth ₹2,000"), and a leaderboard

Under the hood: Python, Streamlit, Damodaran's public industry data, Yahoo Finance, Screener.in and SEC EDGAR. The AI (Gemini free tier, Claude locally) only describes and translates. Every number is computed in code, shown and editable.

Try it: <app link>
Code: <GitHub link>

Can you find a believable story that gets Maruti to ₹15,000? There's a challenge for that.

Educational project, not investment advice.

#Valuation #Damodaran #DCF #FinancialModeling #ProductManagement #Python #AI

---

## Shorter version (if the long one feels heavy)

Can Maruti Suzuki triple in 3 years? My Damodaran-style valuation game says it needs either 54% annual growth or a 33% margin, three times what Indian carmakers earn. The AI's three "routes to 3×" all come back possible at best.

Tell it a story and it turns your words into cars sold, margins, capital and a value per share, then grades your story against reality. Free, with Excel exports that have live formulas.

Try it: <app link> · Code: <GitHub link>
