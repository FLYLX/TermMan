#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  scripts/init-env.sh [--force]

Generate .env files from every .env-example file in this repository.

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

created=0
skipped=0

find "$repo_root" \
  -path "$repo_root/.git" -prune -o \
  -path "$repo_root/node_modules" -prune -o \
  -name ".env-example" -type f -print |
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
done

echo "Done."
