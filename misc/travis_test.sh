#!/bin/bash

set -eux

pip install -e .

rm ~/.birdseye_test.db || true

export BIRDSEYE_SERVER_RUNNING=true
export BIRDSEYE_DB=sqlite:///$HOME/.birdseye_test.db
gunicorn -b 127.0.0.1:7777 birdseye.server:app &

set +e

python setup.py test
result=$?
kill $(ps aux | grep birdseye.server:app | grep -v grep | awk '{print $2}')
exit ${result}
