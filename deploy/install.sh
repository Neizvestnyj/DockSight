#!/bin/sh
# Install or update DockSight with Docker Compose.
#
#   curl -fsSL https://github.com/Neizvestnyj/DockSight/releases/latest/download/install.sh | sh
#
# Settings (environment variables):
#   DOCKSIGHT_DIR         Install directory. Default: ~/.docksight
#   DOCKSIGHT_PORT        Local web port. Default: 8080
#   DOCKSIGHT_COMPONENTS  all (default) or backend for the API only
#   DOCKSIGHT_API_PORT    Local API port in backend-only mode. Default: 8000
#   DOCKSIGHT_PROJECT     Docker Compose project name. Default: docksight
#
# Rerunning the installer of a newer release updates DockSight and keeps .env.
set -eu

RELEASE_TAG='__DOCKSIGHT_RELEASE_TAG__'
COMPOSE_SHA256='__DOCKSIGHT_COMPOSE_SHA256__'
REPOSITORY_URL='https://github.com/Neizvestnyj/DockSight'
MIN_COMPOSE_VERSION='2.24.0'
OVERRIDE_MARKER='# Managed by the DockSight installer.'

say() {
  printf 'docksight: %s\n' "$*"
}

die() {
  printf 'docksight: error: %s\n' "$*" >&2
  exit 1
}

# Succeed when version $1 is at least version $2. Both use MAJOR.MINOR.PATCH.
version_at_least() {
  old_ifs=$IFS
  IFS=.
  # shellcheck disable=SC2086
  set -- $1 $2
  IFS=$old_ifs
  [ "$#" -eq 6 ] || return 1
  for part in "$@"; do
    case $part in '' | *[!0-9]*) return 1 ;; esac
  done
  [ "$1" -gt "$4" ] && return 0
  [ "$1" -lt "$4" ] && return 1
  [ "$2" -gt "$5" ] && return 0
  [ "$2" -lt "$5" ] && return 1
  [ "$3" -ge "$6" ]
}

check_port() {
  case $2 in '' | *[!0-9]*) die "$1 must be a port number." ;; esac
  if [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then
    die "$1 must be between 1 and 65535."
  fi
}

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 -o "$2" "$1" || die "Cannot download $1"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$2" "$1" || die "Cannot download $1"
  else
    die "Install curl or wget first."
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d ' ' -f 1
  else
    openssl dgst -sha256 "$1" | sed 's/^.*= *//'
  fi
}

# Set KEY=VALUE in .env, replacing an existing line and keeping every other line and the file mode.
set_env() {
  awk -v key="$1" -v value="$2" '
    index($0, key "=") == 1 { if (!done) print key "=" value; done = 1; next }
    { print }
    END { if (!done) print key "=" value }
  ' .env > .env.next
  cat .env.next > .env
  rm -f .env.next
}

env_value() {
  sed -n "s/^$1=//p" .env | tail -n 1
}

check_docker() {
  command -v docker >/dev/null 2>&1 \
    || die "Docker is not installed. See https://docs.docker.com/get-started/get-docker/"
  docker info >/dev/null 2>&1 \
    || die "Docker is not running, or this user cannot use it. Start Docker or add the user to the docker group."
  compose_version=$(docker compose version --short 2>/dev/null | sed 's/^v//') \
    || die "Docker Compose v2 is not installed."
  version_at_least "$compose_version" "$MIN_COMPOSE_VERSION" \
    || die "Docker Compose $MIN_COMPOSE_VERSION or later is required, found ${compose_version:-none}."
}

download_release() {
  base=${DOCKSIGHT_RELEASE_URL:-$REPOSITORY_URL/releases/download/$RELEASE_TAG}
  staging=$(mktemp -d "${TMPDIR:-/tmp}/docksight.XXXXXX")
  trap 'rm -rf "$staging"' EXIT
  for name in compose.yaml docksight.env.example INSTALL.md; do
    fetch "$base/$name" "$staging/$name"
  done
  case $COMPOSE_SHA256 in
    __*) say "Skipping the compose.yaml checksum for an unrendered installer." ;;
    *)
      [ "$(sha256_of "$staging/compose.yaml")" = "$COMPOSE_SHA256" ] \
        || die "compose.yaml does not match the release checksum. Nothing was changed."
      ;;
  esac
  for name in compose.yaml docksight.env.example INSTALL.md; do
    cp "$staging/$name" "./$name"
  done
}

docker_socket_group() {
  backend_image=$(sed -n 's/^ *image: *\([^ ]*docksight-backend[^ ]*\) *$/\1/p' compose.yaml | head -n 1)
  [ -n "$backend_image" ] || die "compose.yaml names no backend image."
  MSYS_NO_PATHCONV=1 docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock \
    --entrypoint stat "$backend_image" -c %g /var/run/docker.sock \
    || die "Cannot read the group of /var/run/docker.sock. DockSight needs the local Docker socket."
}

create_env() {
  token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  [ "${#token}" -eq 64 ] || die "Cannot generate an API token."
  docker_gid=$(docker_socket_group | tr -d '\r')
  old_umask=$(umask)
  umask 077
  cp docksight.env.example .env
  umask "$old_umask"
  chmod 600 .env
  set_env DOCKSIGHT_API_TOKEN "$token"
  set_env DOCKSIGHT_DOCKER_GID "$docker_gid"
  set_env DOCKSIGHT_HTTP_PORT "${DOCKSIGHT_PORT:-8080}"
  set_env DOCKSIGHT_BROWSER_ORIGIN "http://127.0.0.1:${DOCKSIGHT_PORT:-8080}"
  new_token=$token
}

apply_overrides() {
  if [ -n "${DOCKSIGHT_PORT:-}" ]; then
    set_env DOCKSIGHT_HTTP_PORT "$DOCKSIGHT_PORT"
    set_env DOCKSIGHT_BROWSER_ORIGIN "http://127.0.0.1:$DOCKSIGHT_PORT"
  fi
  [ -z "${DOCKSIGHT_API_PORT:-}" ] || set_env DOCKSIGHT_API_PORT "$DOCKSIGHT_API_PORT"
  [ -z "${DOCKSIGHT_COMPONENTS:-}" ] || set_env DOCKSIGHT_COMPONENTS "$DOCKSIGHT_COMPONENTS"
  [ -z "${DOCKSIGHT_PROJECT:-}" ] || set_env COMPOSE_PROJECT_NAME "$DOCKSIGHT_PROJECT"
}

write_backend_override() {
  cat > compose.override.yaml <<EOF
$OVERRIDE_MARKER Rerun it with DOCKSIGHT_COMPONENTS=all to remove this file.
services:
  backend:
    ports:
      - "127.0.0.1:\${DOCKSIGHT_API_PORT:-8000}:8000"
EOF
}

remove_backend_override() {
  if [ -f compose.override.yaml ] && grep -q "^$OVERRIDE_MARKER" compose.override.yaml; then
    rm -f compose.override.yaml
  fi
}

start() {
  if [ "$components" = "backend" ]; then
    write_backend_override
    docker compose up --detach --wait --remove-orphans backend || die "DockSight did not start. See: docker compose logs"
    docker compose rm --stop --force web >/dev/null 2>&1 || true
  else
    remove_backend_override
    docker compose up --detach --wait --remove-orphans || die "DockSight did not start. See: docker compose logs"
  fi
}

report() {
  version=$RELEASE_TAG
  case $version in __*) version='development build' ;; esac
  say "DockSight $version is running in $install_dir."
  if [ "$components" = "backend" ]; then
    api_port=$(env_value DOCKSIGHT_API_PORT)
    say "API: http://127.0.0.1:${api_port:-8000}/api/v1"
  else
    say "Open http://127.0.0.1:$(env_value DOCKSIGHT_HTTP_PORT) and choose Connect API."
  fi
  if [ -n "$new_token" ]; then
    say "API token: $new_token"
    say "The token is also stored in $install_dir/.env."
  else
    say "Your settings and API token in $install_dir/.env are unchanged."
  fi
  say "Diagnoses need a model. The default is Ollama on this computer. See $install_dir/INSTALL.md."
  say "Update: rerun this installer. Stop: cd $install_dir && docker compose down"
}

main() {
  [ -z "${DOCKSIGHT_PORT:-}" ] || check_port DOCKSIGHT_PORT "$DOCKSIGHT_PORT"
  [ -z "${DOCKSIGHT_API_PORT:-}" ] || check_port DOCKSIGHT_API_PORT "$DOCKSIGHT_API_PORT"
  case ${DOCKSIGHT_COMPONENTS:-all} in all | backend) ;; *) die "DOCKSIGHT_COMPONENTS must be all or backend." ;; esac
  case $RELEASE_TAG in
    __*) [ -n "${DOCKSIGHT_RELEASE_URL:-}" ] || die "This is an installer template. Use install.sh from a release." ;;
  esac
  check_docker

  install_dir=${DOCKSIGHT_DIR:-${HOME:?Set HOME or DOCKSIGHT_DIR}/.docksight}
  mkdir -p "$install_dir"
  cd "$install_dir"
  install_dir=$(pwd)
  download_release

  new_token=''
  [ -f .env ] || create_env
  apply_overrides
  components=$(env_value DOCKSIGHT_COMPONENTS)
  components=${components:-all}
  case $components in all | backend) ;; *) die "DOCKSIGHT_COMPONENTS in .env must be all or backend." ;; esac

  start
  report
}

main "$@"
