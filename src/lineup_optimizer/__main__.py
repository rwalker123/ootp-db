"""CLI entry point: python -m lineup_optimizer <save_name> [philosophy] [L|R] [team_query]"""

import sys

from .report import generate_lineup_report

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m lineup_optimizer <save_name> [philosophy] [L|R] [team_query]")
        sys.exit(1)
    save = sys.argv[1]
    phil = sys.argv[2] if len(sys.argv) > 2 else "modern"
    hd   = sys.argv[3] if len(sys.argv) > 3 else None
    tq   = sys.argv[4] if len(sys.argv) > 4 else None
    path, data = generate_lineup_report(save, team_query=tq, philosophy=phil, opponent_hand=hd)
    if path is None:
        print("ERROR: Team or data not found")
        sys.exit(1)
    print(f"CACHED:{path}" if data is None else f"GENERATED:{path}")
