from __future__ import annotations
from .application.command_bus import CommandBus
from .application.commands import (
    CreateExperienceCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
    RecordFeedbackCommand,
    AnalyzeQualityCommand,
    SearchCommand,
    RecordSessionCommand,
    GetStatsCommand,
    InferAdoptionCommand,
    ExtractExperienceCommand,
    ListExperiencesCommand,
    DeleteExperienceCommand,
    GetExperienceCommand,
)
from .application.handlers.experience_handler import ExperienceHandler
from .application.handlers.feedback_handler import FeedbackHandler
from .application.handlers.search_handler import SearchHandler
from .application.handlers.session_handler import SessionHandler
from .application.handlers.stats_handler import StatsHandler
from .application.handlers.infer_adoption_handler import InferAdoptionHandler
from .application.handlers.extract_handler import ExtractHandler
from .application.handlers.experience_query_handler import ExperienceQueryHandler
from .application.handlers.analyze_handler import AnalyzeHandler
from .infrastructure.unit_of_work import UnitOfWork


class _SimpleLLM:
    def generate_title(self, text: str) -> str:
        import os
        try:
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("XP_LLM_API_KEY")
            if not api_key:
                return text[:60]
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=os.getenv("XP_LLM_API_BASE"))
            resp = client.chat.completions.create(
                model=os.getenv("XP_LLM_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": f"用10-15个字总结以下任务，只输出标题，不加标点：\n{text}"}],
                max_tokens=30,
                temperature=0,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return text[:60]


class _MetadataInferrer:
    def infer(self, text: str) -> dict:
        from .domain.metadata import infer_tech_stack, infer_scene, infer_level
        return {
            "tech_stack": infer_tech_stack(text),
            "scene": infer_scene(text),
            "level": infer_level(text, text).value,
        }


def build_command_bus(project: str = "default") -> CommandBus:
    llm = _SimpleLLM()
    metadata = _MetadataInferrer()

    experience_handler = ExperienceHandler(
        uow_factory=UnitOfWork,
        llm=llm,
        metadata_inferrer=metadata,
    )
    feedback_handler = FeedbackHandler(uow_factory=UnitOfWork)
    search_handler = SearchHandler(uow_factory=UnitOfWork, project=project)
    session_handler = SessionHandler(uow_factory=UnitOfWork)
    stats_handler = StatsHandler(uow_factory=UnitOfWork)
    infer_adoption_handler = InferAdoptionHandler(uow_factory=UnitOfWork)
    extract_handler = ExtractHandler(uow_factory=UnitOfWork, project=project)
    query_handler = ExperienceQueryHandler(uow_factory=UnitOfWork)
    analyze_handler = AnalyzeHandler(uow_factory=UnitOfWork)

    bus = CommandBus()
    bus.register(CreateExperienceCommand, experience_handler.handle_create)
    bus.register(ActivateExperienceCommand, experience_handler.handle_activate)
    bus.register(ArchiveExperienceCommand, experience_handler.handle_archive)
    bus.register(RecordFeedbackCommand, feedback_handler.handle_feedback)
    bus.register(SearchCommand, search_handler.handle_search)
    bus.register(RecordSessionCommand, session_handler.handle_record_session)
    bus.register(GetStatsCommand, stats_handler.handle_get_stats)
    bus.register(InferAdoptionCommand, infer_adoption_handler.handle_infer_adoption)
    bus.register(ExtractExperienceCommand, extract_handler.handle_extract)
    bus.register(ListExperiencesCommand, query_handler.handle_list)
    bus.register(DeleteExperienceCommand, query_handler.handle_delete)
    bus.register(GetExperienceCommand, query_handler.handle_get)
    bus.register(AnalyzeQualityCommand, analyze_handler.handle_analyze)

    return bus
