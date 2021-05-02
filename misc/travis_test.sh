#!/bin/bash

set -eux

sudo cp node_modules/chromedriver/lib/chromedriver/chromedriver /usr/local/bin/chromedriver

cd birdseye/static/
python -m http.server 7778 &
cd -

pytest -vv
result=$?
kill $(ps aux | grep http.server | grep -v grep | awk '{print $2}')
exit ${result}
