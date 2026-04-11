"""CLI entry point: python -m rotation_analysis <save> [mode] [openers=N] [team]

Examples:
  python -m rotation_analysis My-Save-2026
  python -m rotation_analysis My-Save-2026 ace-first
  python -m rotation_analysis My-Save-2026 balanced opener
  python -m rotation_analysis My-Save-2026 innings openers=2
  python -m rotation_analysis My-Save-2026 six-man Cleveland
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rotation_analysis.report import generate_rotation_report


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m rotation_analysis <save_name> [mode] [opener|openers=N] [team]")
        sys.exit(1)

    save = sys.argv[1]
    raw  = " ".join(sys.argv[2:])
    raw_lower = raw.lower()

    # Parse mode
    mode = next(
        (m for m in ("ace-first", "innings", "six-man", "balanced") if m in raw_lower),
        "balanced",
    )

    # Parse openers=N or bare "opener"
    m = re.search(r'openers?\s*=\s*(\d)', raw_lower)
    n_openers = int(m.group(1)) if m else (1 if "opener" in raw_lower else 0)

    # Parse excluded names: "without <name>"
    excluded = [
        mg.group(1).strip()
        for mg in re.finditer(r'without\s+([A-Za-z][A-Za-z\s\-\']+?)(?=\s+(?:without|with\b|include|$))', raw, re.I)
    ]

    # Parse forced names: "with <name>" / "include <name>"
    forced = [
        mg.group(1).strip()
        for mg in re.finditer(r'(?:with|include)\s+([A-Za-z][A-Za-z\s\-\']+?)(?=\s+(?:without|with\b|include|$))', raw, re.I)
    ]

    # Strip known tokens to isolate optional team name
    stop = (r'(?:balanced|ace-first|innings|six-man|openers?\s*=\s*\d|\bopener\b'
            r'|without\s+[A-Za-z][A-Za-z\s\-\']+'
            r'|(?:with|include)\s+[A-Za-z][A-Za-z\s\-\']+)')
    team_query = re.sub(stop, '', raw, flags=re.I).strip(" ,") or None

    six_man = mode == "six-man"

    path, data = generate_rotation_report(
        save,
        team_query=team_query,
        mode=mode,
        n_openers=n_openers,
        six_man=six_man,
        excluded_names=excluded,
        forced_names=forced,
        raw_args=raw,
    )
    if path is None:
        print("ERROR: Team not found or insufficient pitcher data", file=sys.stderr)
        sys.exit(1)

    prefix = "CACHED" if data is None else "GENERATED"
    print(f"{prefix}:{path}")


if __name__ == "__main__":
    main()
