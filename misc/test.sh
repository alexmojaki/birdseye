#!/bin/bash

set -eux

cd birdseye/static/
python -m http.server 7778 &
cd -

python -m pytest -vv
result=$?
kill $(ps aux | grep http.server | grep -v grep | awk '{print $2}')
exit ${result}
