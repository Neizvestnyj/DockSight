#!/usr/bin/env bash
# Install DockSight with the rendered release installer from a local release directory.
# Usage: scripts/test_release_installer.sh BACKEND_IMAGE FRONTEND_IMAGE
#
# Covers a fresh install, a rerun that keeps settings, switching to backend-only, and a tampered download.
# Creates only uniquely named Compose projects and temporary directories, and removes exactly those on exit.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: test_release_installer.sh BACKEND_IMAGE FRONTEND_IMAGE" >&2
  exit 2
fi

backend_image=$1
frontend_image=$2
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
installer="$root/deploy/install.sh"
if [ ! -f "$installer" ]; then
  echo "Installer is missing: deploy/install.sh" >&2
  exit 1
fi

owner=$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')
project="docksight-install-$owner"
tampered_project="docksight-install-tampered-$owner"
port=$((20000 + RANDOM % 5000))
api_port=$((25000 + RANDOM % 5000))
origin="http://127.0.0.1:$port"
work=$(mktemp -d)
target="$work/target"
tampered_target="$work/tampered-target"

log() {
  printf 'installer-test: %s\n' "$*" >&2
}

fail() {
  log "FAIL: $*"
  exit 1
}

file_url() {
  if command -v cygpath >/dev/null 2>&1; then
    printf 'file:///%s' "$(cygpath -m "$1")"
  else
    printf 'file://%s' "$1"
  fi
}

cleanup() {
  local status=$?
  for directory in "$target" "$tampered_target"; do
    if [ -f "$directory/compose.yaml" ]; then
      if [ "$status" -ne 0 ]; then
        (cd "$directory" && docker compose logs --no-color --tail 60 >&2) || true
      fi
      (cd "$directory" && docker compose down --volumes --remove-orphans --timeout 5 >/dev/null 2>&1) || true
    fi
  done
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

# Write a local release directory like the published assets.
release_dir() {
  local directory=$1
  mkdir -p "$directory"
  "$root/scripts/render_release_compose.sh" "$root/deploy/compose.yaml" "$backend_image" "$frontend_image" \
    > "$directory/compose.yaml"
  cp "$root/deploy/docksight.env.example" "$root/deploy/INSTALL.md" "$directory/"
  "$root/scripts/render_release_installer.sh" "$installer" v0.0.0-ci "$directory/compose.yaml" \
    > "$directory/install.sh"
}

env_value() {
  sed -n "s/^$1=//p" "$2/.env" | tail -n 1
}

running_services() {
  (cd "$target" && docker compose ps --status running --services)
}

release_dir "$work/release"
url=$(file_url "$work/release")

log "fresh install into a new directory"
DOCKSIGHT_DIR="$target" DOCKSIGHT_PROJECT="$project" DOCKSIGHT_PORT="$port" DOCKSIGHT_API_PORT="$api_port" \
  DOCKSIGHT_RELEASE_URL="$url" sh "$work/release/install.sh" > "$work/first.txt"
token=$(env_value DOCKSIGHT_API_TOKEN "$target")
[[ $token =~ ^[0-9a-f]{64}$ ]] || fail "the installer did not generate a 64-character token"
grep -q "$token" "$work/first.txt" || fail "the first install did not print the token"
if [ "$(uname -s)" = "Linux" ]; then
  [ "$(stat -c %a "$target/.env")" = "600" ] || fail ".env is readable by other users"
fi
[ -n "$(docker ps -q --filter "label=com.docker.compose.project=$project")" ] \
  || fail "Compose did not use the project name saved in .env"
curl -fsS --max-time 10 "$origin/health/live" | grep -q '"status":"ok"' || fail "web proxy health failed"
curl -fsS --max-time 10 -X POST -H "Authorization: Bearer $token" -H "Origin: $origin" \
  -H 'Content-Type: application/json' --data '{}' "$origin/api/v1/auth/login" | grep -q '"actor":"operator"' \
  || fail "login with the generated token failed"

log "rerun keeps the token and settings"
printf '# kept by rerun\n' >> "$target/.env"
DOCKSIGHT_DIR="$target" DOCKSIGHT_RELEASE_URL="$url" sh "$work/release/install.sh" > "$work/second.txt"
[ "$(env_value DOCKSIGHT_API_TOKEN "$target")" = "$token" ] || fail "rerun changed the token"
grep -q '^# kept by rerun$' "$target/.env" || fail "rerun rewrote .env"
if grep -q "$token" "$work/second.txt"; then
  fail "rerun printed the existing token"
fi
curl -fsS --max-time 10 "$origin/health/live" | grep -q '"status":"ok"' || fail "health failed after rerun"

log "switch to backend-only"
DOCKSIGHT_DIR="$target" DOCKSIGHT_COMPONENTS=backend DOCKSIGHT_RELEASE_URL="$url" sh "$work/release/install.sh" \
  > "$work/backend.txt"
[ "$(env_value DOCKSIGHT_COMPONENTS "$target")" = "backend" ] || fail "backend-only mode was not saved"
curl -fsS --max-time 10 "http://127.0.0.1:$api_port/health/live" | grep -q '"status":"ok"' \
  || fail "backend-only API port is unreachable"
[ "$(running_services | tr -d '\r')" = "backend" ] || fail "backend-only mode left other services running"

log "a tampered compose.yaml is rejected before anything starts"
release_dir "$work/tampered"
printf '# tampered\n' >> "$work/tampered/compose.yaml"
"$root/scripts/render_release_installer.sh" "$installer" v0.0.0-ci "$work/release/compose.yaml" \
  > "$work/tampered/install.sh"
if DOCKSIGHT_DIR="$tampered_target" DOCKSIGHT_PROJECT="$tampered_project" \
  DOCKSIGHT_RELEASE_URL="$(file_url "$work/tampered")" sh "$work/tampered/install.sh" > "$work/tampered.txt" 2>&1; then
  fail "the installer accepted a tampered compose.yaml"
fi
grep -qi 'checksum' "$work/tampered.txt" || fail "the tampered download did not report a checksum error"
[ ! -e "$tampered_target/.env" ] || fail "the tampered install created .env"
[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$tampered_project")" ] \
  || fail "the tampered install started containers"

log "PASS"
