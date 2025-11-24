#!/bin/bash

# Set up environment for local development
export PATH="/Users/benlang/.local/bin:$PATH"
export PKG_CONFIG_PATH="$(brew --prefix cairo)/lib/pkgconfig:$PKG_CONFIG_PATH"
export DYLD_LIBRARY_PATH="$(brew --prefix cairo)/lib:$DYLD_LIBRARY_PATH"

# Change to src directory
cd "$(dirname "$0")/src"

# Run the Flask app on port 5001 (5000 is often used by AirPlay on macOS)
echo "Starting Flask app on http://localhost:5001"
poetry run python3 -c "from main import app; app.run(debug=True, port=5001, host='127.0.0.1')"

