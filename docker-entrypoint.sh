#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data
    chown -R broker:broker /app/data
    exec gosu broker "$@"
fi

exec "$@"
