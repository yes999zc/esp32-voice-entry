#!/bin/zsh
# launchd entrypoint: exec makes the Python server the managed process, so a
# restart cannot orphan a child that keeps ports 4410/4411 occupied.
repo_root=${0:A:h:h}
cd "$repo_root/src" || exit 1

if [[ -f "$HOME/.hermes/.env" ]]; then
    set -a
    source "$HOME/.hermes/.env" 2>/dev/null
    set +a
fi
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
exec "$repo_root/.venv313/bin/python" server.py --config "$repo_root/config.yaml"
