from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="xp-server", version="0.3.0")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
