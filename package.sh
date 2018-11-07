#!/bin/bash

set -ex

rm -rf dist/ || true

python3.5 setup.py sdist
python3.5 -m twine check dist/*
python3.5 setup.py sdist upload
