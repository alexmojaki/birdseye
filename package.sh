#!/bin/bash

set -e

python3.5 setup.py sdist

read -p "Upload? " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
  BIRDSEYE_DB=sqlite:///:memory: BIRDSEYE_TESTING_IN_MEMORY=true python3.5 setup.py test sdist upload
fi
