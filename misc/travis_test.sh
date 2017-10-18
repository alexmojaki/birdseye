#!/bin/bash

set -eux

rm ~/.birdseye_test.db || true

export BIRDSEYE_SERVER_RUNNING=true

gunicorn -b 127.0.0.1:7777 birdseye.server:app &
sleep 3

set +e

python setup.py test
result=$?
kill $(ps aux | grep birdseye.server:app | grep -v grep | awk '{print $2}')
exit ${result}
