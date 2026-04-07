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
    SearchV2Command,
    SaveCommand,
    FeedbackV2Command,
    ScanPromotionCandidatesCommand,
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
from .application.handlers.search_v2_handler import SearchV2Handler
from .application.handlers.save_handler import SaveHandler
from .application.handlers.feedback_v2_handler import FeedbackV2Handler
from .application.handlers.promotion_handler import PromotionScanHandler
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


async def build_command_bus(project: str = "default", dsn: str = None) -> CommandBus:
    import os
    from .infrastructure.backends.postgres import PostgresBackend

    resolved_dsn = dsn or os.environ.get("DATABASE_URL")
    if not resolved_dsn:
        raise RuntimeError("DATABASE_URL environment variable is required")

    backend = PostgresBackend(dsn=resolved_dsn)
    def uow_factory():
        return UnitOfWork(backend=backend)

    llm = _SimpleLLM()
    metadata = _MetadataInferrer()

    experience_handler = ExperienceHandler(
        uow_factory=uow_factory,
        llm=llm,
        metadata_inferrer=metadata,
    )
    feedback_handler = FeedbackHandler(uow_factory=uow_factory)
    search_handler = SearchHandler(uow_factory=uow_factory, project=project)
    session_handler = SessionHandler(uow_factory=uow_factory)
    stats_handler = StatsHandler(uow_factory=uow_factory)
    infer_adoption_handler = InferAdoptionHandler(uow_factory=uow_factory)
    extract_handler = ExtractHandler(uow_factory=uow_factory, project=project)
    query_handler = ExperienceQueryHandler(uow_factory=uow_factory)
    analyze_handler = AnalyzeHandler(uow_factory=uow_factory)

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

    from .embeddings import get_provider
    embedding_provider = get_provider()

    search_v2_handler = SearchV2Handler(
        backend=backend,
        llm=None,
        embedding_provider=embedding_provider,
    )
    save_handler_v2 = SaveHandler(
        uow_factory=uow_factory,
        llm=None,
    )
    feedback_v2_handler = FeedbackV2Handler(
        uow_factory=uow_factory,
        backend=backend,
        llm=None,
    )

    bus.register(SearchV2Command, search_v2_handler.handle)
    bus.register(SaveCommand, save_handler_v2.handle)
    bus.register(FeedbackV2Command, feedback_v2_handler.handle)

    promotion_handler = PromotionScanHandler(
        uow_factory=uow_factory,
        embedding_provider=embedding_provider,
    )
    bus.register(ScanPromotionCandidatesCommand, promotion_handler.handle)

    return bus


def build_command_bus(  # type: ignore[no-redef]
    backend=None,
    llm=None,
    embedding_provider=None,
) -> CommandBus:
    bus = CommandBus()

    if backend is not None:
        def uow_factory():
            return UnitOfWork(backend=backend)

        bus.register(
            SearchV2Command,
            SearchV2Handler(backend=backend, llm=llm, embedding_provider=embedding_provider).handle,
        )
        bus.register(
            SaveCommand,
            SaveHandler(uow_factory=uow_factory, llm=llm).handle,
        )
        bus.register(
            FeedbackV2Command,
            FeedbackV2Handler(uow_factory=uow_factory, backend=backend, llm=llm).handle,
        )

    return bus
