#!/usr/bin/env bash

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
IMPORT_EXIT=$?

if [ "$1" = "list" ]; then
    exit 0
fi

SAVE_NAME="$1"

if [ $IMPORT_EXIT -ne 0 ]; then
    python src/update_status.py "$SAVE_NAME" failed import
    exit $IMPORT_EXIT
fi

FAILED_STEPS=()

python src/analytics.py "$@"    || FAILED_STEPS+=("analytics")
python src/ratings.py "$@"      || FAILED_STEPS+=("ratings")
python src/draft_ratings.py "$@" || FAILED_STEPS+=("draft_ratings")
python src/ifa_ratings.py "$@"  || FAILED_STEPS+=("ifa_ratings")

if [ ${#FAILED_STEPS[@]} -eq 0 ]; then
    python src/update_status.py "$SAVE_NAME" ok
else
    python src/update_status.py "$SAVE_NAME" partial "${FAILED_STEPS[@]}"
fi
