"""Points: Damodaran rewards stories that are bold but stay within limits.

  boldness     how far the story moves value from the status quo: a 3x (or 1/3) move or more is fully bold
  plausibility the story-vs-reality score (0-100), squared so red flags hurt a lot
  points       1000 x boldness x plausibility^2
A timid story earns little; a wild one with red flags earns little; a big move every driver can defend wins.
"""
import math

FULL_BOLD = math.log(3)


def boldness(value: float, status_quo: float) -> float:
    """0-1: the size of the move from the status quo, on a log scale."""
    if value <= 0 or status_quo <= 0:
        return 1.0 if value > 0 >= status_quo else 0.0
    return min(abs(math.log(value / status_quo)) / FULL_BOLD, 1.0)


def points(value: float, status_quo: float, score: int) -> int:
    return round(1000 * boldness(value, status_quo) * (score / 100) ** 2)


def challenge_points(score: int) -> int:
    """A met challenge already sets the boldness; the more defensible the story, the more points (min 100)."""
    return max(100, round(1000 * (score / 100) ** 2))
