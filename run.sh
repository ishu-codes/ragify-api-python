#!/usr/bin/env bash

set -e

BASE_URL='http://localhost:8000'
BASE_URL_API="$BASE_URL/api/v1"
MONGO_PATH="mongodb://myuser:mypassword@localhost:27017/ragify?authSource=admin"

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Install exactly what uv.lock pins: runtime deps, plus the "dev" dependency
# group (OpenTelemetry, Prometheus) and the "dev" extra (pytest). This creates
# .venv if it is missing and repairs it if it is damaged.
#
# --frozen makes uv refuse to rewrite the lockfile, so a pyproject.toml/lock
# mismatch fails loudly instead of silently leaving a half-installed venv.
uv sync --frozen --group dev --extra dev

source .venv/bin/activate

export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

case "$1" in
    dev)
        fastapi dev main.py
    ;;

    ragify-server)
        cd ../rag && .venv/bin/python -m src.grpc
    ;;

    #  curl commands
    root)
        curl -X GET $BASE_URL
    ;;


    # Auth
    register)
        curl -i -X POST $BASE_URL_API/auth/register \
        -H "Content-Type: application/json" \
        -d "{
                \"name\": \"$2\",
                \"email\": \"$2@email.com\",
                \"password\": \"${2}@123456\"
            }"
    ;;

    login)
        curl -i -X POST $BASE_URL_API/auth/login \
        -H "Content-Type: application/json" \
        -d "{
                \"email\": \"$2@email.com\",
                \"password\": \"${2}@123456\"
            }"
    ;;


    # workspaces
    list)
        curl -X GET $BASE_URL_API/workspaces/ \
        -H "Authorization: Bearer $2"
    ;;

    create)
        curl -X POST $BASE_URL_API/workspaces/ \
        -H "Authorization: Bearer $2"
    ;;

    upload)
        curl -X POST $BASE_URL_API/docs/upload/ \
        -H "Authorization: Bearer $2" \
        -H "Content-Type: application/json" \
        -d '{
                "session_id": "123abc"
            }'
    ;;

    query)
        curl -X POST $BASE_URL_API/query/ \
        -H "Authorization: Bearer $2" \
        -H "Content-Type: application/json" \
        -d '{
                "session_id": "123abc",
                "query": "What is Rag?"
            }'
    ;;

    # Data initialization
    create_collections)
        mongosh $MONGO_PATH --eval '
            db.createCollection("users")
            db.createCollection("workspaces")
            db.createCollection("sessions")
        '
    ;;

    # Delete collections
    drop_collections)
        mongosh $MONGO_PATH --eval '
            db.users.drop()
            db.workspaces.drop()
            db.sessions.drop()
        '
    ;;

    # insert_workspace)
    #     db.workspaces.insertOne({
    #         user_id: $2,

    #     })

    *)
        echo "Usage: $0 {dev|root|upload|query}"
        exit 1
    ;;
esac
