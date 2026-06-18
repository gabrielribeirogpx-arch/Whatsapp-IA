#!/bin/bash
set -euo pipefail

if [ -f backend/release.sh ]; then
  echo "Backend release context detected at ./backend; running migrations..."
  exec bash backend/release.sh
fi

if [ -f release.sh ] && [ -f scripts/run_release_migrations.py ]; then
  echo "Backend release context detected in current directory; running migrations..."
  exec bash release.sh
fi

echo "No backend release context detected; skipping migrations"
exit 0
