#!/usr/bin/env bash
# Render the distributable Compose file by replacing only the two image placeholders.
# Usage: scripts/render_release_compose.sh TEMPLATE BACKEND_IMAGE FRONTEND_IMAGE > compose.yaml
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: render_release_compose.sh TEMPLATE BACKEND_IMAGE FRONTEND_IMAGE" >&2
  exit 2
fi

template=$1
backend=$2
frontend=$3
reference='^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9_][A-Za-z0-9._-]{0,127})?(@sha256:[0-9a-f]{64})?$'

for image in "$backend" "$frontend"; do
  if ! [[ $image =~ $reference ]]; then
    echo "Invalid image reference: $image" >&2
    exit 2
  fi
done

placeholders=$(grep -cE '\$\{DOCKSIGHT_(BACKEND|FRONTEND)_IMAGE:\?[^}]*\}' "$template" || true)
if [ "$placeholders" != "2" ]; then
  echo "Expected exactly two image placeholders in $template, found $placeholders." >&2
  exit 1
fi

sed -E \
  -e "s#\\$\\{DOCKSIGHT_BACKEND_IMAGE:\\?[^}]*\\}#${backend}#" \
  -e "s#\\$\\{DOCKSIGHT_FRONTEND_IMAGE:\\?[^}]*\\}#${frontend}#" \
  "$template"
