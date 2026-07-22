#!/bin/sh
set -e

# Crée les répertoires de données et de logs s'ils n'existent pas encore.
# Avec un bind-mount, cela les crée aussi côté hôte au premier démarrage.
mkdir -p "${RAW_DATA_FOLDER:-/app/data/raw}"
mkdir -p "${PROCESSED_DATA_FOLDER:-/app/data/processed}"
mkdir -p "$(dirname "${LOG_FILE:-/app/logs/app.log}")"

exec python main.py
