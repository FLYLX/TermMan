#!/bin/sh
set -e

node /opt/napcat/napcat.mjs &
NAPCAT_PID=$!

termpaws run &
TERMPAWS_PID=$!

trap 'kill $NAPCAT_PID $TERMPAWS_PID 2>/dev/null' TERM INT
wait -n $NAPCAT_PID $TERMPAWS_PID
EXIT_CODE=$?
kill $NAPCAT_PID $TERMPAWS_PID 2>/dev/null
exit $EXIT_CODE
