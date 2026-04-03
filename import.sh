#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

pip install -q -r requirements.txt

if [ ! -f .env ]; then
    echo "Error: .env not found. Creating from .env.example..."
    cp .env.example .env
    echo "Edit .env with your paths, then re-run this script."
    exit 1
fi

python src/import.py "$@"

if [ "$1" = "list" ]; then
    exit 0
fi

python src/analytics.py "$@"
python src/ratings.py "$@"
python src/draft_ratings.py "$@"
python src/ifa_ratings.py "$@"
