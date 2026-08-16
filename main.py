import sys
from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from apps.api.src.auth.controller import router as auth_router
from apps.api.src.config.db import (
    close_database_connection,
    connect_to_database,
    db_manager,
)
from apps.api.src.workspace.controller import router as workspace_router

load_dotenv()


def _get_cors_origins() -> list[str]:
    origins = getenv("CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in origins.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_manager = db_manager
    await connect_to_database()
    yield
    await close_database_connection()

    from apps.api.src.ragify_client import client as ragify_client

    ragify_client.close()


app = FastAPI(title="Ragify", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(HTTPException)
async def global_http_exception_handler(_: Request, exception: HTTPException):
    return JSONResponse(
        status_code=exception.status_code, content={"detail": exception.detail}
    )


@app.exception_handler(Exception)
async def global_exception_handler(_: Request, exception: Exception):
    return JSONResponse(status_code=500, content={"detail": str(exception)})


@app.get("/")
async def read_root():
    return {
        "name": "ragify",
        "version": "0.1",
        "project": "https://github.com/ishu-codes/ragify",
        "author": "Ishu Kumar",
    }


app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(workspace_router, prefix="/api/v1/workspaces", tags=["Workspace"])
