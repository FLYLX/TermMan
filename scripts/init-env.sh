#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  scripts/init-env.sh [--force]

Generate .env files from every .env-example file in this repository.
When robot/.env is first generated, its bridge token is copied from the
root .env ROBOT_BRIDGE_SHARED_SECRET, or SECRET_KEY if no bridge token exists.

Options:
  -f, --force   Overwrite existing .env files.
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

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
examples_file=$(mktemp)
trap 'rm -f "$examples_file"' EXIT HUP INT TERM

created=0
skipped=0
robot_env_touched=0

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

sync_robot_bridge_secret() {
  robot_env_path=$repo_root/robot/.env
  root_env_path=$repo_root/.env

  [ -f "$robot_env_path" ] || return 0

  if bridge_secret=$(read_env_value "$root_env_path" ROBOT_BRIDGE_SHARED_SECRET); then
    set_env_value "$robot_env_path" ROBOT_BRIDGE_SHARED_SECRET "$bridge_secret"
    echo "sync   robot/.env bridge token from .env ROBOT_BRIDGE_SHARED_SECRET"
  elif bridge_secret=$(read_env_value "$root_env_path" SECRET_KEY); then
    set_env_value "$robot_env_path" ROBOT_BRIDGE_SHARED_SECRET "$bridge_secret"
    echo "sync   robot/.env bridge token from .env SECRET_KEY"
  fi
}

find "$repo_root" \
  -path "$repo_root/.git" -prune -o \
  -path "$repo_root/node_modules" -prune -o \
  -name ".env-example" -type f -print | sort > "$examples_file"

while IFS= read -r example_file; do
  env_file=$(dirname "$example_file")/.env
  rel_example=${example_file#"$repo_root/"}
  rel_env=${env_file#"$repo_root/"}

  if [ -f "$env_file" ] && [ "$force" -ne 1 ]; then
    echo "skip   $rel_env already exists (from $rel_example)"
    skipped=$((skipped + 1))
    continue
  fi

  cp "$example_file" "$env_file"
  echo "write  $rel_env (from $rel_example)"
  created=$((created + 1))

  if [ "$rel_env" = "robot/.env" ]; then
    robot_env_touched=1
  fi
done < "$examples_file"

if [ "$robot_env_touched" -eq 1 ]; then
  sync_robot_bridge_secret
fi

echo "Done."
