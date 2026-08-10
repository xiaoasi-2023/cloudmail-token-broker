#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    exec gosu broker "$@"
fi

exec "$@"
