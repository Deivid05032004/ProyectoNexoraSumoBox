from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import verificar_conexion

from routers.categories import router as categories_router
app = FastAPI(
    title="UTA SUMO ROBOTICS CUP API",
    description="API para gestionar inscripciones y administración del torneo.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories_router)

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
