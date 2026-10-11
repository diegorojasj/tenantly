#!/bin/sh
# Refresh the services' translation catalogs, then compile them (common/i18n.py).
#
#   scripts/messages.sh            extract new strings into every .po, then compile
#   scripts/messages.sh compile    only compile (after editing a .po)
#
# Catalogs: common/locale (shared errors) and <service>/src/locale. Edit the
# `msgstr` lines of the .po files; commit both the .po and the compiled .mo,
# since the service images don't carry the gettext tools.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
MANAGE="$ROOT/identity-service/manage.py"
export DEBUG=1

for dir in common identity-service/src operations-service/src billing-service/src; do
  mkdir -p "$ROOT/$dir/locale"
  cd "$ROOT/$dir"
  if [ "$1" != "compile" ]; then
    "$PY" "$MANAGE" makemessages --locale es --no-obsolete --ignore 'migrations/*' --ignore 'tests/*' --ignore 'locale/*'
  fi
  "$PY" "$MANAGE" compilemessages --locale es
done
