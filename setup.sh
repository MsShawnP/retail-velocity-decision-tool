#!/usr/bin/env bash
set -e

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required to build the database but was not found."
    echo "Install Python 3 from https://www.python.org/downloads/ and re-run this script."
    exit 1
fi

# Pull the data generation submodule
git submodule update --init --recursive

# Create a virtual environment for data generation (avoids polluting global packages)
python3 -m venv .venv
source .venv/bin/activate

# Install data generation dependencies
pip install -r data/cinderhaven-data/requirements.txt

# Build the database into the project's data/ folder
python data/cinderhaven-data/scripts/build_db.py --output ./data/cinderhaven_product_master.db

deactivate
echo "Done. Database built at data/cinderhaven_product_master.db"
