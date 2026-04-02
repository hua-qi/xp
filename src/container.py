from __future__ import annotations
from .application.command_bus import CommandBus
from .application.commands import (
    CreateExperienceCommand,
    ActivateExperienceCommand,
    ArchiveExperienceCommand,
    RecordFeedbackCommand,
    AnalyzeQualityCommand,
)
from .application.handlers.experience_handler import ExperienceHandler
from .application.handlers.feedback_handler import FeedbackHandler
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


def build_command_bus() -> CommandBus:
    llm = _SimpleLLM()
    metadata = _MetadataInferrer()

    experience_handler = ExperienceHandler(
        uow_factory=UnitOfWork,
        llm=llm,
        metadata_inferrer=metadata,
    )
    feedback_handler = FeedbackHandler(uow_factory=UnitOfWork)

    bus = CommandBus()
    bus.register(CreateExperienceCommand, experience_handler.handle_create)
    bus.register(ActivateExperienceCommand, experience_handler.handle_activate)
    bus.register(ArchiveExperienceCommand, experience_handler.handle_archive)
    bus.register(RecordFeedbackCommand, feedback_handler.handle_feedback)

    return bus
