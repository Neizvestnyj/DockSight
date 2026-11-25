#!/usr/bin/env bash
# Smoke-test the packaged DockSight Compose deployment with a pair of local images.
# Usage: scripts/smoke_release_compose.sh BACKEND_IMAGE FRONTEND_IMAGE
#
# Requires bash, curl, Docker, and Docker Compose v2. Creates only one uniquely named Compose project with its own
# volume and network, and removes exactly that project on exit.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: smoke_release_compose.sh BACKEND_IMAGE FRONTEND_IMAGE" >&2
  exit 2
fi

backend_image=$1
frontend_image=$2
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
template="$root/deploy/compose.yaml"
stub="$root/scripts/release_model_stub.py"
render="$root/scripts/render_release_compose.sh"

for fixture in "$template" "$stub" "$render" "$root/frontend/Dockerfile" "$root/frontend/nginx.conf"; do
  if [ ! -f "$fixture" ]; then
    echo "Packaged fixture is missing: ${fixture#"$root"/}" >&2
    exit 1
  fi
done

expected_version=${DOCKSIGHT_EXPECTED_VERSION:-$(sed -n 's/^version = "\(.*\)"$/\1/p' "$root/backend/pyproject.toml" | head -n 1)}
owner=$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')
project="docksight-smoke-$owner"
token=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
port=${DOCKSIGHT_SMOKE_PORT:-$((20000 + RANDOM % 10000))}
origin="http://127.0.0.1:$port"
work=$(mktemp -d)
stream_pid=""

log() {
  printf 'smoke: %s\n' "$*" >&2
}

compose() {
  (cd "$work" && docker compose --project-name "$project" -f compose.yaml -f smoke.override.yaml "$@")
}

cleanup() {
  local status=$?
  if [ -n "$stream_pid" ]; then
    kill "$stream_pid" 2>/dev/null || true
  fi
  if [ "$status" -ne 0 ] && [ -f "$work/compose.yaml" ]; then
    log "failed; recent service logs follow"
    compose logs --no-color --tail 80 >&2 || true
  fi
  if [ -f "$work/compose.yaml" ]; then
    compose down --volumes --remove-orphans --timeout 5 >/dev/null 2>&1 || true
  fi
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

fail() {
  log "FAIL: $*"
  exit 1
}

# Poll a command until it succeeds or the deadline in seconds passes.
wait_for() {
  local seconds=$1
  shift
  local deadline=$((SECONDS + seconds))
  until "$@"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      return 1
    fi
    sleep 0.5
  done
}

stream_has() {
  grep -q "$1" "$work/stream.txt"
}

session_is_restored() {
  curl -fsS --max-time 5 -b "$work/cookies.txt" "$origin/api/v1/auth/session" 2>/dev/null \
    | grep -q '"actor":"operator"'
}

log "project $project on $origin"
"$render" "$template" "$backend_image" "$frontend_image" > "$work/compose.yaml"
cp "$stub" "$work/release_model_stub.py"

docker_gid=$(MSYS_NO_PATHCONV=1 docker run --rm --label "com.docksight.test=$owner" \
  --volume /var/run/docker.sock:/var/run/docker.sock --entrypoint stat "$backend_image" -c %g /var/run/docker.sock)

cat > "$work/.env" <<EOF
DOCKSIGHT_API_TOKEN=$token
DOCKSIGHT_DOCKER_GID=$docker_gid
DOCKSIGHT_HTTP_PORT=$port
DOCKSIGHT_BROWSER_ORIGIN=$origin
DOCKSIGHT_COOKIE_SECURE=false
DOCKSIGHT_PROVIDER=ollama
DOCKSIGHT_MODEL=smoke-model
DOCKSIGHT_MODEL_BASE_URL=http://model-stub:11434
DOCKSIGHT_MODEL_TIMEOUT=120
EOF

cat > "$work/smoke.override.yaml" <<EOF
services:
  backend:
    labels:
      com.docksight.test: "$owner"
    depends_on:
      model-stub:
        condition: service_started
  web:
    labels:
      com.docksight.test: "$owner"
  model-stub:
    image: $backend_image
    entrypoint: ["python", "/stub/release_model_stub.py"]
    labels:
      com.docksight.test: "$owner"
    volumes:
      - type: bind
        source: ./release_model_stub.py
        target: /stub/release_model_stub.py
        read_only: true
  smoke-target:
    image: $backend_image
    entrypoint: ["python", "-c", "import time; time.sleep(3600)"]
    labels:
      com.docksight.test: "$owner"
      com.docksight.smoke-target: "$owner"
EOF

if grep -q 'build:' "$work/compose.yaml"; then
  fail "the distributed Compose file must not contain build instructions"
fi
compose config --quiet
compose up --detach --wait --wait-timeout 180

log "web root serves the production bundle"
curl -fsS --max-time 10 "$origin/" > "$work/index.html" || fail "web root is unreachable on $origin"
grep -q '<div id="root"></div>' "$work/index.html" || fail "web root does not serve index.html"
if grep -q '/src/main.tsx' "$work/index.html"; then
  fail "web root serves the development entry point"
fi
asset=$(grep -o '/assets/[^"]*\.js' "$work/index.html" | head -n 1)
[ -n "$asset" ] || fail "index.html references no built JavaScript asset"
curl -fsS --max-time 10 -o /dev/null "$origin$asset" || fail "built asset $asset is not served"
curl -fsS --max-time 10 "$origin/investigations/unknown" | grep -q '<div id="root"></div>' \
  || fail "client routes do not fall back to index.html"

log "health reports version $expected_version through the web proxy"
curl -fsS --max-time 10 "$origin/health/live" | grep -q "\"version\":\"$expected_version\"" \
  || fail "health does not report version $expected_version"

log "first-party cookie login on one origin"
curl -fsS --max-time 10 -c "$work/cookies.txt" -b "$work/cookies.txt" -X POST \
  -H "Authorization: Bearer $token" -H "Origin: $origin" -H 'Content-Type: application/json' --data '{}' \
  "$origin/api/v1/auth/login" | grep -q '"actor":"operator"' || fail "cookie login failed"
grep -q 'docksight_session' "$work/cookies.txt" || fail "login did not set the session cookie"
session_is_restored || fail "the cookie session is not readable"

log "non-root backend reads a labeled test container"
[ "$(compose exec -T backend id -u | tr -d '\r')" = "10001" ] || fail "backend does not run as UID 10001"
curl -fsS --max-time 30 -b "$work/cookies.txt" "$origin/api/v1/hosts/local/containers" > "$work/containers.json" \
  || fail "backend cannot list Docker containers"
grep -q "$project-smoke-target-1" "$work/containers.json" || fail "labeled test container is missing from inventory"

log "API stream delivers its first event before the model replies"
curl -sS -N --compressed --max-time 150 -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' --data '{"host":"local","query":"Summarize the smoke test host"}' \
  "$origin/api/v1/chat/turns" > "$work/stream.txt" 2>&1 &
stream_pid=$!
wait_for 30 stream_has 'turn.started' || fail "no SSE event arrived while the model reply was held"
if stream_has 'turn.completed' || stream_has 'turn.failed'; then
  fail "the turn ended before the model reply was released"
fi
compose exec -T model-stub python -c "open('/tmp/docksight-smoke-release', 'w').close()"
if ! wait_for 120 stream_has 'turn.completed'; then
  cat "$work/stream.txt" >&2
  fail "the stream did not complete after the model reply was released"
fi
wait "$stream_pid" || true
stream_pid=""

log "cookie session survives backend recreation with fresh anonymous volumes"
compose up --detach --wait --wait-timeout 180 --force-recreate --renew-anon-volumes --no-deps backend
wait_for 30 session_is_restored || fail "the cookie session was not restored after backend recreation"

log "PASS"
