import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from rich.markup import escape as rich_escape

from app.core.auth import router as auth
from app.core.database import engine, init_db
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.logging_config import setup_logging
from app.middleware.logging_middleware import logging_middleware

logger = logging.getLogger(__name__)

setup_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield
    await engine.dispose()


# from app.routers import
# from app.ws.connections import router as ws

load_dotenv()
app = FastAPI(lifespan=lifespan)

origins = ["http://localhost:5173", "http://localhost:5174"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(logging_middleware)


@app.exception_handler(AuthenticationError)
async def auth_error_handler(_request: Request, exc: AuthenticationError):
    logger.warning(
        "[red]Authentication failed:[/] %s",
        rich_escape(exc.args[0] if exc.args else "unknown"),
    )
    return JSONResponse(
        status_code=401,
        content={"detail": exc.args[0] if exc.args else "Authentication failed"},
    )


@app.exception_handler(ConflictError)
async def conflict_error_handler(_request: Request, exc: ConflictError):
    logger.warning(
        "[yellow]Conflict:[/] %s",
        rich_escape(exc.args[0] if exc.args else "unknown"),
    )
    return JSONResponse(
        status_code=409, content={"detail": exc.args[0] if exc.args else "Conflict"}
    )


app.include_router(auth)

# --- router marker ---