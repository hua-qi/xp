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
    ScanPromotionCandidatesCommand,
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
    async def health():
        return {"status": "ok"}

    @app.post("/api/experiences", status_code=201)
    async def extract_experience(req: ExtractRequest):
        bus = await build_command_bus()
        try:
            exp = await bus.dispatch(ExtractExperienceCommand(
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
    async def search_experiences(
        q: str,
        top_k: int = 3,
        session_id: Optional[str] = None,
        tags: Optional[str] = None,
    ):
        bus = await build_command_bus()
        tag_list = tags.split(",") if tags else None
        results, meta = await bus.dispatch(SearchCommand(
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
    async def list_experiences(status: str = "pending"):
        bus = await build_command_bus()
        try:
            exps = await bus.dispatch(ListExperiencesCommand(status=status))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"experiences": [{"id": e.id, "title": e.title, "status": e.status.value,
                                  "confidence": e.confidence} for e in exps]}

    @app.patch("/api/experiences/{exp_id}")
    async def review_experience(exp_id: str, req: ReviewRequest):
        bus = await build_command_bus()
        if req.action == "activate":
            success = await bus.dispatch(ActivateExperienceCommand(experience_id=exp_id))
        elif req.action == "archive":
            success = await bus.dispatch(ArchiveExperienceCommand(experience_id=exp_id, reason=req.reason or ""))
        else:
            raise HTTPException(400, f"Unknown action: {req.action}")
        if not success:
            raise HTTPException(404, "Experience not found")
        return {"status": "ok"}

    @app.post("/api/feedback")
    async def record_feedback(req: FeedbackRequest):
        bus = await build_command_bus()
        success = await bus.dispatch(RecordFeedbackCommand(
            experience_id=req.experience_id,
            helpful=req.adopted,
        ))
        if not success:
            raise HTTPException(404, "Experience not found")
        return {"status": "ok"}

    @app.post("/api/sessions")
    async def record_session(req: SessionRequest):
        bus = await build_command_bus()
        await bus.dispatch(RecordSessionCommand(
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
    async def get_stats(since: Optional[int] = None):
        bus = await build_command_bus()
        return await bus.dispatch(GetStatsCommand(since_days=since))

    @app.post("/api/infer-adoption")
    async def infer_adoption(req: InferAdoptionRequest):
        bus = await build_command_bus()
        results = await bus.dispatch(InferAdoptionCommand(
            session_id=req.session_id,
            final_response=req.final_response,
            experience_ids_injected=req.experience_ids_injected,
        ))
        return {"results": results}

    class PromoteScopeRequest(BaseModel):
        target_scope: str
        target_scope_id: str

    @app.post("/api/promotion/scan")
    async def scan_promotion_candidates(dry_run: bool = False):
        bus = await build_command_bus()
        return await bus.dispatch(ScanPromotionCandidatesCommand(dry_run=dry_run))

    @app.post("/api/promotion/{exp_id}/promote")
    async def promote_experience(exp_id: str, req: PromoteScopeRequest):
        bus = await build_command_bus()
        success = await bus.dispatch(ActivateExperienceCommand(experience_id=exp_id))
        if not success:
            raise HTTPException(404, "Experience not found")
        return {"status": "ok", "experience_id": exp_id, "target_scope": req.target_scope}

    return app
