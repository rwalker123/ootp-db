"""Module-level constants shared across lineup_optimizer sub-modules."""

from config import WOBA_HBP

# lineup_optimizer uses WOBA_HP as local alias (other modules use WOBA_HBP)
WOBA_HP = WOBA_HBP

PHILOSOPHIES = ("modern", "traditional", "platoon", "hot-hand")
PHIL_LABELS = {
    "modern": "Modern / Sabermetric",
    "traditional": "Traditional",
    "platoon": "Platoon",
    "hot-hand": "Hot Hand",
}
