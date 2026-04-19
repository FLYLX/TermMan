#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

LEGACY_ALEMBIC_REVISION="$(python app/alembic_compat.py)"
if [ -n "${LEGACY_ALEMBIC_REVISION}" ]; then
    alembic stamp "${LEGACY_ALEMBIC_REVISION}"
fi

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py
