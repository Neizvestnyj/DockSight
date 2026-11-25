#!/usr/bin/env bash
# Render a release installer with its release tag and the sha256 of the release compose.yaml.
# Usage: scripts/render_release_installer.sh TEMPLATE TAG COMPOSE_FILE > installer
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: render_release_installer.sh TEMPLATE TAG COMPOSE_FILE" >&2
  exit 2
fi

template=$1
tag=$2
compose=$3

if ! [[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]]; then
  echo "Invalid release tag: $tag" >&2
  exit 2
fi

if command -v sha256sum >/dev/null 2>&1; then
  checksum=$(sha256sum "$compose" | cut -d ' ' -f 1)
else
  checksum=$(shasum -a 256 "$compose" | cut -d ' ' -f 1)
fi

for placeholder in __DOCKSIGHT_RELEASE_TAG__ __DOCKSIGHT_COMPOSE_SHA256__; do
  if ! grep -q "$placeholder" "$template"; then
    echo "$template has no $placeholder placeholder." >&2
    exit 1
  fi
done

sed -e "s/__DOCKSIGHT_RELEASE_TAG__/$tag/g" -e "s/__DOCKSIGHT_COMPOSE_SHA256__/$checksum/g" "$template"
