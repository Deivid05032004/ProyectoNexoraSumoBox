from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
import logging

from database import verificar_conexion
from app.core.config import ALLOWED_ORIGINS, MAX_RECEIPT_BYTES

from routers.categories import router as categories_router
from routers.auth import router as auth_router
from routers.catalogs import router as catalogs_router
from routers.resources import router as resources_router
from routers.registrations import router as registrations_router
from routers.payments import router as payments_router
from routers.admin import router as admin_router
from routers.reports import router as reports_router
class ReceiptUploadSizeLimit:
    """Bound receipt bodies even when clients omit Content-Length or use chunks."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes + 256 * 1024  # multipart headers and boundaries

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or not scope["path"].startswith("/api/v1/payments/")
                or not scope["path"].endswith("/receipt")):
            await self.app(scope, receive, send)
            return

        raw_length = next((value.decode("latin-1") for key, value in scope.get("headers", [])
                           if key.lower() == b"content-length"), None)
        if raw_length is not None:
            try:
                if int(raw_length) > self.max_bytes:
                    response = JSONResponse(status_code=413, content={"detail": "La solicitud supera el tamaño máximo permitido."})
                    await response(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse(status_code=400, content={"detail": "Content-Length inválido."})
                await response(scope, receive, send)
                return

        messages = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    response = JSONResponse(status_code=413, content={"detail": "La solicitud supera el tamaño máximo permitido."})
                    await response(scope, receive, send)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break

        index = 0

        async def replay_receive():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


app = FastAPI(
    title="UTA SUMO ROBOTICS CUP API",
    description="API para gestionar inscripciones y administración del torneo.",
    version="1.0.0",
)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request, exc):
    # SQLAlchemy engine hides bind values; never return SQL or driver details to clients.
    logging.getLogger("uta_sumo_api.database").error(
        "Database operation failed for %s %s", request.method, request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(status_code=503, content={
        "detail": "No se pudo completar la operación en la base de datos."
    })


app.add_middleware(ReceiptUploadSizeLimit, max_bytes=MAX_RECEIPT_BYTES)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Page", "X-Page-Size", "X-Total-Pages"],
)

app.include_router(categories_router)
app.include_router(auth_router)
app.include_router(catalogs_router)
app.include_router(resources_router)
app.include_router(registrations_router)
app.include_router(payments_router)
app.include_router(admin_router)
app.include_router(reports_router)

@app.get("/")
def inicio():
    return {
        "mensaje": "API UTA SUMO ROBOTICS CUP funcionando",
        "estado": "correcto",
    }


@app.get("/api/v1/health")
def health():
    try:
        base_datos = verificar_conexion()
        return {
            "status": "ok",
            "database": "connected",
            "database_name": base_datos,
        }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con la base de datos.",
        )


@app.get("/api/v1/health/live")
def liveness():
    return {"status": "ok"}
