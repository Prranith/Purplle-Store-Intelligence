#!/bin/bash
# Purplle Store Intelligence Challenge 2026
# Orchestration script — processes all 5 CCTV clips and uploads events to the API.
# Usage: bash pipeline/run.sh [--clip-dir=<path>] [--clip-start=<ISO>] [--api=<url>]

set -euo pipefail

CLIP_DIR="footage/"
CLIP_START="2026-04-10T10:00:00+05:30"
API_URL="http://localhost:8000"

# Parse arguments
for i in "$@"
do
case $i in
    --clip-dir=*)
    CLIP_DIR="${i#*=}"
    shift
    ;;
    --clip-start=*)
    CLIP_START="${i#*=}"
    shift
    ;;
    --api=*)
    API_URL="${i#*=}"
    shift
    ;;
    *)
    # unknown option
    ;;
esac
done

echo "Launching store-intelligence video analysis..."
echo "  Clip directory : $CLIP_DIR"
echo "  Clip start time: $CLIP_START"
echo "  Target API     : $API_URL"
echo ""

# Resolve python binary (python3 preferred; fall back to python)
PYTHON_BIN=""
if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
else
    echo "ERROR: Neither python3 nor python found in PATH." >&2
    exit 1
fi

echo "Using Python: $($PYTHON_BIN --version)"
echo ""

# Run the detection pipeline
"$PYTHON_BIN" "$(dirname "$0")/detect.py" \
    --clip-dir="$CLIP_DIR" \
    --clip-start="$CLIP_START" \
    --api="$API_URL"
