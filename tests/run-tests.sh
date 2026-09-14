#!/bin/bash

# Helper script to run tests from any directory
# This ensures the tests always run from the correct directory

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change to the tests directory
cd "$SCRIPT_DIR"

# Run the test runner with all arguments passed through
./scripts/test-runner.sh "$@"