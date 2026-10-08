#!/usr/bin/env bash
# Builds the single Lambda zip folder: our code + runtime deps for arm64 / Python 3.13.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf build && mkdir build
cp -r src/teesri build/
if grep -Eq '^[^#[:space:]]' requirements.txt; then
  uv pip install --quiet --target build --python-platform aarch64-manylinux2014 \
    --python-version 3.13 --only-binary :all: -r requirements.txt
fi
find build -name __pycache__ -type d -prune -exec rm -rf {} +
echo "build/ ready"
