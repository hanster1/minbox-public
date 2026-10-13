#!/bin/bash
# Portable read-only diagnostics. Does not install dependencies or repair state.
set -eu
support_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1; then
        exec "$candidate" "$support_dir/mac_support.py" "$@"
    fi
done
printf '%s\n' '{"ok":false,"error_code":"python_unavailable","error":"Python 3.9 or newer is required for the read-only report."}'
exit 1
