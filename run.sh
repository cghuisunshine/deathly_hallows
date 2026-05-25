#!/usr/bin/env bash
set -euo pipefail

python3 -m tools.reader_pipeline all "$@"
