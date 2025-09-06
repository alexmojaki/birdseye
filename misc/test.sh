#!/bin/bash

set -eux

export DB=${DB:-sqlite}

if [ ${DB} = sqlite ]; then
    rm ~/.birdseye_test.db || true
    export BIRDSEYE_DB=sqlite:///$HOME/.birdseye_test.db
elif [ ${DB} = postgres ]; then
    psql -c 'DROP DATABASE IF EXISTS birdseye_test;' -U postgres
    psql -c 'CREATE DATABASE birdseye_test;' -U postgres
    export BIRDSEYE_DB="postgresql://postgres:@localhost/birdseye_test"
elif [ ${DB} = mysql ]; then
    mysql -e 'DROP DATABASE IF EXISTS birdseye_test;'
    mysql -e 'CREATE DATABASE birdseye_test;'
    export BIRDSEYE_DB="mysql+mysqlconnector://root:@localhost/birdseye_test"
else
    echo "Unknown database $DB"
    exit 1
fi

python -m gunicorn -b 127.0.0.1:7777 birdseye.server:app &

set +e

python -m pytest -vv
result=$?
kill $(ps aux | grep birdseye.server:app | grep -v grep | awk '{print $2}')
exit ${result}
