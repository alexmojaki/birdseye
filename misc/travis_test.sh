#!/bin/bash

sudo cp node_modules/chromedriver/lib/chromedriver/chromedriver /usr/local/bin/chromedriver

pip install -e .

./misc/test.sh
