#!/bin/bash

set -ex

python3.5 setup.py sdist
python3.5 -m twine check dist/*
python3.5 setup.py sdist upload
