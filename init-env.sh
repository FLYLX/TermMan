#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  sh ./init-env.sh [--force]

Generate .env files from every .env-example in the repository.

Rules:
  1. The repository root .env is the Docker Compose source of truth.
  2. Component .env files are generated in their own directories.
  3. Shared values that appear in both places are synced from root .env
     into component .env files so they cannot drift.

Currently synced:
  - .env VITE_API_URL -> frontend/.env VITE_API_URL
  - .env ROBOT_BRIDGE_PUBLIC_URL -> robot/.env ROBOT_BRIDGE_PUBLIC_URL
  - .env ROBOT_BRIDGE_SHARED_SECRET -> robot/.env ROBOT_BRIDGE_SHARED_SECRET
    falling back to .env SECRET_KEY when no bridge secret is set.

Options:
  -f, --force   Overwrite existing .env files from .env-example first.
  -h, --help    Show this help.
EOF
}

force=0

for arg in "$@"; do
  case "$arg" in
    -f|--force)
      force=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
examples_file=$(mktemp)
trap 'rm -f "$examples_file"' EXIT HUP INT TERM

read_env_value() {
  env_path=$1
  env_key=$2

  [ -f "$env_path" ] || return 1

  env_value=$(
    awk -v key="$env_key" '
      /^[[:space:]]*#/ { next }
      $0 ~ "^[[:space:]]*" key "=" {
        sub("^[[:space:]]*" key "=", "")
        sub(/\r$/, "")
        print
      }
    ' "$env_path" | tail -n 1
  )

  [ -n "$env_value" ] || return 1
  printf '%s\n' "$env_value"
}

set_env_value() {
  env_path=$1
  env_key=$2
  env_value=$3
  tmp_path="${env_path}.tmp.$$"

  awk -v key="$env_key" -v value="$env_value" '
    BEGIN { found = 0 }
    $0 ~ "^[[:space:]]*" key "=" {
      print key "=" value
      found = 1
      next
    }
    { print }
    END {
      if (!found) {
        print key "=" value
      }
    }
  ' "$env_path" > "$tmp_path"
  mv "$tmp_path" "$env_path"
}

copy_env_example() {
  example_file=$1
  env_file=$2
  rel_example=${example_file#"$repo_root/"}
  rel_env=${env_file#"$repo_root/"}

  if [ -f "$env_file" ] && [ "$force" -ne 1 ]; then
    echo "skip   $rel_env already exists (from $rel_example)"
    return 0
  fi

  mkdir -p "$(dirname "$env_file")"
  cp "$example_file" "$env_file"
  echo "write  $rel_env (from $rel_example)"
}

sync_frontend_env() {
  root_env_path=$repo_root/.env
  frontend_env_path=$repo_root/frontend/.env

  [ -f "$frontend_env_path" ] || return 0

  if vite_api_url=$(read_env_value "$root_env_path" VITE_API_URL); then
    set_env_value "$frontend_env_path" VITE_API_URL "$vite_api_url"
    echo "sync   frontend/.env VITE_API_URL from .env"
  fi

}

sync_robot_env() {
  root_env_path=$repo_root/.env
  robot_env_path=$repo_root/robot/.env

  [ -f "$robot_env_path" ] || return 0


  if bridge_public_url=$(read_env_value "$root_env_path" ROBOT_BRIDGE_PUBLIC_URL); then
    set_env_value "$robot_env_path" ROBOT_BRIDGE_PUBLIC_URL "$bridge_public_url"
    echo "sync   robot/.env ROBOT_BRIDGE_PUBLIC_URL from .env"
  fi
  if bridge_secret=$(read_env_value "$root_env_path" ROBOT_BRIDGE_SHARED_SECRET); then
    set_env_value "$robot_env_path" ROBOT_BRIDGE_SHARED_SECRET "$bridge_secret"
    echo "sync   robot/.env bridge token from .env ROBOT_BRIDGE_SHARED_SECRET"
  elif bridge_secret=$(read_env_value "$root_env_path" SECRET_KEY); then
    set_env_value "$robot_env_path" ROBOT_BRIDGE_SHARED_SECRET "$bridge_secret"
    echo "sync   robot/.env bridge token from .env SECRET_KEY"
  fi
}

root_example=$repo_root/.env-example
root_env=$repo_root/.env

if [ ! -f "$root_example" ]; then
  echo "Missing root .env-example: $root_example" >&2
  exit 1
fi

copy_env_example "$root_example" "$root_env"

find "$repo_root" \
  -path "$repo_root/.git" -prune -o \
  -path "$repo_root/node_modules" -prune -o \
  -name ".env-example" -type f -print | sort > "$examples_file"

while IFS= read -r example_file; do
  if [ "$example_file" = "$root_example" ]; then
    continue
  fi

  env_file=$(dirname "$example_file")/.env
  copy_env_example "$example_file" "$env_file"
done < "$examples_file"

sync_frontend_env
sync_robot_env

echo "Done."