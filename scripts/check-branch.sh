#!/bin/sh
branch=$(git symbolic-ref --short HEAD 2>/dev/null)
if [ "$branch" = "main" ]; then
  echo "Error: direct commits to main are not allowed. Create a branch first:"
  echo "  git checkout -b feat/your-feature"
  exit 1
fi
