#!/usr/bin/env bash
set -euo pipefail
cd frontend
npm run lint >/tmp/autoresearch-check-lint.out 2>&1 || { tail -80 /tmp/autoresearch-check-lint.out; exit 1; }
npm run build >/tmp/autoresearch-check-build.out 2>&1 || { tail -80 /tmp/autoresearch-check-build.out; exit 1; }
