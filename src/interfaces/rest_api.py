from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.storage import ExperienceStore, MetricsStore
from src.knowledge import KnowledgeService


class ExtractRequest(BaseModel):
    task_description: str
    solution_summary: str
    key_decisions: str
    conversation_summary: Optional[str] = None
    tags: list = []
    related_files: list = []


def create_app() -> FastAPI:
    app = FastAPI(title="xp-server", version="0.3.0")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/experiences", status_code=201)
    async def extract_experience(req: ExtractRequest):
        store = ExperienceStore()
        metrics = MetricsStore()
        svc = KnowledgeService(store, metrics)
        try:
            exp = await svc.extract_experience(
                task_description=req.task_description,
                solution_summary=req.solution_summary,
                key_decisions=req.key_decisions,
                conversation_summary=req.conversation_summary,
                tags=req.tags,
                related_files=req.related_files,
            )
            return {
                "id": exp.id,
                "status": exp.status.value,
                "confidence": exp.confidence,
                "title": exp.title,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return app
