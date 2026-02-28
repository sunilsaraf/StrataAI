#!/usr/bin/env bash
# Initialize the AI control keyspace in Cassandra.
# Usage: ./init.sh [cassandra-host]

set -euo pipefail

HOST="${1:-cassandra}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Waiting for Cassandra at ${HOST}:9042 …"
until cqlsh "${HOST}" -e "DESCRIBE KEYSPACES" &>/dev/null; do
    sleep 3
done

echo "Applying AI control schema …"
cqlsh "${HOST}" -f "${SCRIPT_DIR}/ai_control_keyspace.cql"
echo "Schema applied successfully."
