import json
from pathlib import Path
from datetime import datetime


def migrate(source_path: Path, dry_run: bool = True) -> int:
    knowledge_file = source_path / "knowledge.json"
    if not knowledge_file.exists():
        print(f"knowledge.json not found at {knowledge_file}")
        return 0

    with open(knowledge_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    from src.storage import ExperienceStore
    from src.models import (
        Experience, ExperienceType, ExperienceLevel,
        ExperienceStatus, ExperienceSource, ExperienceMetadata,
    )

    count = 0
    for exp_id, exp_data in data.items():
        if dry_run:
            print(f"[dry-run] Would migrate: {exp_id[:8]} - {exp_data.get('title', '?')}")
            count += 1
            continue

        meta_data = exp_data.get("metadata", {})
        exp = Experience(
            id=exp_data["id"],
            type=ExperienceType(exp_data.get("type", "feature")),
            level=ExperienceLevel(exp_data.get("level", "L2")),
            title=exp_data.get("title", ""),
            tags=exp_data.get("tags", []),
            problem=exp_data.get("problem", ""),
            solution=exp_data.get("solution", ""),
            key_decisions=exp_data.get("key_decisions", ""),
            confidence=exp_data.get("confidence", 0.6),
            status=ExperienceStatus(exp_data.get("status", "pending")),
            source=ExperienceSource(exp_data.get("source", "agent")),
            created_at=exp_data.get("created_at", datetime.utcnow().isoformat()),
            related_files=exp_data.get("related_files", []),
            metadata=ExperienceMetadata(
                tech_stack=meta_data.get("tech_stack", []),
                problem_type=meta_data.get("problem_type", ""),
                scene=meta_data.get("scene", []),
            ),
            project=exp_data.get("project", "default"),
            last_hit_at=exp_data.get("last_hit_at"),
        )

        store = ExperienceStore()
        store.add(exp)

        from src.embeddings import get_provider
        from src.storage import VectorStore
        provider = get_provider()
        exp_text = f"{exp.title}\n{exp.problem}\n{exp.key_decisions}"
        vec = provider.embed_text(exp_text)
        VectorStore().save_vector(exp.id, vec)

        count += 1
        print(f"Migrated: {exp_id[:8]} - {exp.title}")

    return count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate knowledge.json to new store")
    parser.add_argument("--source", default="~/.xp", help="Source XP_HOME path")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true", default=False)
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    dry = not args.execute
    count = migrate(source_path=source, dry_run=dry)
    print(f"\nTotal: {count} experiences {'(dry-run)' if dry else 'migrated'}")
