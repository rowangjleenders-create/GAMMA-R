#!/usr/bin/env bash
# One-shot iOS preview build for GAMMA-R (requires Apple Developer + eas login).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "→ Checking eas-cli…"
npx eas-cli whoami || { echo "Run: npx eas-cli login"; exit 1; }
if grep -q 'TODO-replace-after-eas-init\|TODO-replace-after-eas-init\|TODO-replace' app.json 2>/dev/null; then
  echo "→ projectId still TODO — run: npx eas-cli init"
  exit 1
fi
echo "→ Starting iOS preview build (device IPA)…"
npx eas-cli build --platform ios --profile preview "$@"
echo "→ Done. Open the Expo build URL → TestFlight / Install."
