#!/usr/bin/env bash

set -e

BASE_URL='http://localhost:8000'
BASE_URL_API="$BASE_URL/api/v1"
MONGO_PATH="mongodb://myuser:mypassword@localhost:27017/ragify?authSource=admin"

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ ! -d ".venv" ]; then
    uv venv .venv
fi

source .venv/bin/activate

uv pip install -q pyyaml pydantic pydotenv langchain-core langchain langchain-ollama langchain-qdrant langgraph langchain-tavily transformers torch qdrant-client fastapi uvicorn "fastapi[standard]" bcrypt pymongo markitdown python-jose passlib pyjwt langchain-text-splitters 2>/dev/null

export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

case "$1" in
    dev)
        fastapi dev main.py
    ;;

    ragify-server)
        python -m src.ragify.grpc
    ;;

    #  curl commands
    root)
        curl -X GET $BASE_URL
    ;;


    # Auth
    register)
        curl -X POST $BASE_URL_API/auth/register \
        -H "Content-Type: application/json" \
        -d "{
                \"name\": \"$2\",
                \"email\": \"$2@email.com\",
                \"password\": \"${2}@1234\"
            }"
    ;;

    login)
        curl -X POST $BASE_URL_API/auth/login \
        -H "Content-Type: application/json" \
        -d "{
                \"email\": \"$2@email.com\",
                \"password\": \"${2}@1234\"
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
