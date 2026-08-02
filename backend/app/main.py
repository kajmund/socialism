from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, personas, populations, runs
from app.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title="Opinionssimulator", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(personas.router)
    app.include_router(populations.router)
    app.include_router(runs.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
