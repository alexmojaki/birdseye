#!/bin/bash

set -eux

sudo npm install --global gulp-cli
npm install gulp gulp-eslint

# Now run `gulp` to lint JS continuously
