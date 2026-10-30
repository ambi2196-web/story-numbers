"""Saved scenarios and the leaderboard, in a local SQLite file (data/game.sqlite)."""
import json
import sqlite3
import time

from app.config import DATA_DIR

DB_PATH = DATA_DIR / "game.sqlite"
SCENARIO_FIELDS = ["player", "symbol", "company", "name", "tag", "kind", "currency", "value_per_share", "price",
                   "status_quo", "growth", "target_margin", "sales_to_capital", "cost_of_capital", "share_y10",
                   "units_y10", "unit_name", "score", "verdict", "points", "headline", "drivers"]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(f"CREATE TABLE IF NOT EXISTS scenarios (id INTEGER PRIMARY KEY, {', '.join(SCENARIO_FIELDS)}, "
                 "created_at REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS leaderboard (id INTEGER PRIMARY KEY, player, challenge, points, "
                 "value_per_share, score, verdict, headline, created_at REAL)")
    return conn


def save_scenario(**fields) -> int:
    fields = {k: fields.get(k) for k in SCENARIO_FIELDS}
    if fields["drivers"] is not None:
        fields["drivers"] = json.dumps(fields["drivers"])
    with _connect() as conn:
        cur = conn.execute(f"INSERT INTO scenarios ({', '.join(SCENARIO_FIELDS)}, created_at) VALUES "
                           f"({', '.join('?' * (len(SCENARIO_FIELDS) + 1))})", [*fields.values(), time.time()])
        return cur.lastrowid


def scenarios(symbol: str, player: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM scenarios WHERE symbol = ? AND player = ? ORDER BY created_at",
                            (symbol, player)).fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["drivers"] = json.loads(r["drivers"]) if r["drivers"] else None
    return out


def delete_scenario(scenario_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))


def submit(player: str, challenge: str, points: int, value_per_share: float, score: int, verdict: str,
           headline: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO leaderboard (player, challenge, points, value_per_share, score, verdict, headline, "
                     "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (player, challenge, points, value_per_share, score, verdict, headline, time.time()))


def leaderboard(challenge: str | None = None, limit: int = 10) -> list[dict]:
    """Best entry per player: for one challenge, or overall (the sum of each player's best per challenge)."""
    with _connect() as conn:
        if challenge:
            rows = conn.execute("SELECT player, MAX(points) AS points, verdict, headline FROM leaderboard "
                                "WHERE challenge = ? GROUP BY player ORDER BY points DESC LIMIT ?",
                                (challenge, limit)).fetchall()
        else:
            rows = conn.execute("SELECT player, SUM(best) AS points, COUNT(*) AS challenges FROM (SELECT player, "
                                "challenge, MAX(points) AS best FROM leaderboard GROUP BY player, challenge) "
                                "GROUP BY player ORDER BY points DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
