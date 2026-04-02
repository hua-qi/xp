from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..container import build_command_bus
from ..application.commands import (
    ExtractExperienceCommand,
    SearchCommand,
    ListExperiencesCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
    RecordFeedbackCommand,
    RecordSessionCommand,
    GetStatsCommand,
    InferAdoptionCommand,
)


class ExtractRequest(BaseModel):
    task_description: str
    solution_summary: str
    key_decisions: str
    conversation_summary: Optional[str] = None
    tags: list = []
    related_files: list = []


class ReviewRequest(BaseModel):
    action: str
    reason: Optional[str] = None


class FeedbackRequest(BaseModel):
    experience_id: str
    adopted: bool
    reason: Optional[str] = None


class SessionRequest(BaseModel):
    session_id: str
    task_description: str
    experience_ids_injected: list = []
    iteration_count: int = 1
    had_error_correction: bool = False
    user_accepted: bool = True
    ab_test_group: str = "treatment"
    result_shown: bool = True


class InferAdoptionRequest(BaseModel):
    session_id: str
    final_response: str
    experience_ids_injected: list = []


def create_app() -> FastAPI:
    app = FastAPI(title="xp-server", version="0.3.0")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/experiences", status_code=201)
    def extract_experience(req: ExtractRequest):
        bus = build_command_bus()
        try:
            exp = bus.dispatch(ExtractExperienceCommand(
                task_description=req.task_description,
                solution_summary=req.solution_summary,
                key_decisions=req.key_decisions,
                conversation_summary=req.conversation_summary,
                tags=req.tags,
                related_files=req.related_files,
            ))
            return {
                "id": exp.id,
                "status": exp.status.value,
                "confidence": exp.confidence,
                "title": exp.title,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/experiences/search")
    def search_experiences(
        q: str,
        top_k: int = 3,
        session_id: Optional[str] = None,
        tags: Optional[str] = None,
    ):
        bus = build_command_bus()
        tag_list = tags.split(",") if tags else None
        results, meta = bus.dispatch(SearchCommand(
            query=q,
            tags=tag_list,
            top_k=top_k,
            session_id=session_id,
        ))
        return {
            "results": [
                {
                    "id": e.id,
                    "title": e.title,
                    "solution": e.solution,
                    "key_decisions": e.key_decisions,
                    "similarity": getattr(e, "similarity", None),
                    "confidence": e.confidence,
                    "tags": e.tags,
                }
                for e in results
            ],
            "metadata": meta,
        }

    @app.get("/api/experiences")
    def list_experiences(status: str = "pending"):
        bus = build_command_bus()
        try:
            exps = bus.dispatch(ListExperiencesCommand(status=status))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"experiences": [{"id": e.id, "title": e.title, "status": e.status.value,
                                  "confidence": e.confidence} for e in exps]}

    @app.patch("/api/experiences/{exp_id}")
    def review_experience(exp_id: str, req: ReviewRequest):
        bus = build_command_bus()
        if req.action == "activate":
            success = bus.dispatch(ActivateExperienceCommand(experience_id=exp_id))
        elif req.action == "archive":
            success = bus.dispatch(ArchiveExperienceCommand(experience_id=exp_id, reason=req.reason or ""))
        else:
            raise HTTPException(400, f"Unknown action: {req.action}")
        if not success:
            raise HTTPException(404, "Experience not found")
        return {"status": "ok"}

    @app.post("/api/feedback")
    def record_feedback(req: FeedbackRequest):
        bus = build_command_bus()
        success = bus.dispatch(RecordFeedbackCommand(
            experience_id=req.experience_id,
            helpful=req.adopted,
        ))
        if not success:
            raise HTTPException(404, "Experience not found")
        return {"status": "ok"}

    @app.post("/api/sessions")
    def record_session(req: SessionRequest):
        bus = build_command_bus()
        bus.dispatch(RecordSessionCommand(
            session_id=req.session_id,
            task_description=req.task_description,
            experience_ids_injected=req.experience_ids_injected,
            iteration_count=req.iteration_count,
            had_error_correction=req.had_error_correction,
            user_accepted=req.user_accepted,
            ab_test_group=req.ab_test_group,
            ab_test_result_shown=req.result_shown,
        ))
        return {"status": "ok"}

    @app.get("/api/stats")
    def get_stats(since: Optional[int] = None):
        bus = build_command_bus()
        return bus.dispatch(GetStatsCommand(since_days=since))

    @app.post("/api/infer-adoption")
    def infer_adoption(req: InferAdoptionRequest):
        bus = build_command_bus()
        results = bus.dispatch(InferAdoptionCommand(
            session_id=req.session_id,
            final_response=req.final_response,
            experience_ids_injected=req.experience_ids_injected,
        ))
        return {"results": results}

    return app
