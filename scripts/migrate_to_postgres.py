#!/usr/bin/env python3
"""
将本地 JSON + SQLite 数据迁移到 PostgreSQL。
支持续跑（checkpoint），支持回滚（切换 XP_BACKEND 即可）。

用法:
    python scripts/migrate_to_postgres.py --dsn postgresql://user:pass@host/dbname
    python scripts/migrate_to_postgres.py --dsn ... --dry-run   # 只预检，不写入
"""
import argparse
import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


async def preflight_check(json_path: Path) -> dict:
    if not json_path.exists():
        return {"total": 0, "missing_vectors": [], "ok": True}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    total = len(data)
    missing_vectors = [eid for eid, v in data.items() if not v.get("solution")]
    return {"total": total, "missing_vectors": missing_vectors, "ok": True}


async def backup_source(xp_home: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = xp_home / "backup" / f"migrate_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["knowledge.json", "metrics.db"]:
        src = xp_home / fname
        if src.exists():
            shutil.copy2(src, backup_dir / fname)
    return backup_dir


async def migrate(dsn: str, xp_home: Path, dry_run: bool = False, batch_size: int = 100):
    from src.backends.postgres import PostgresBackend
    from src.storage import ExperienceStore, VectorStore
    from src.models import ExperienceStatus

    json_path = xp_home / "knowledge.json"
    checkpoint_path = xp_home / "migrate_checkpoint.json"

    print("=== Pre-flight check ===")
    result = await preflight_check(json_path)
    print(f"Source total: {result['total']} experiences")
    if result["missing_vectors"]:
        print(f"Warning: {len(result['missing_vectors'])} experiences missing solution field")

    if dry_run:
        print("[DRY RUN] No data will be written.")
        return

    print("\n=== Backing up source data ===")
    backup_dir = await backup_source(xp_home)
    print(f"Backup saved to: {backup_dir}")

    migrated_ids: set[str] = set()
    if checkpoint_path.exists():
        migrated_ids = set(json.loads(checkpoint_path.read_text())["migrated"])
        print(f"Resuming from checkpoint: {len(migrated_ids)} already migrated")

    backend = PostgresBackend(dsn)
    await backend.connect()

    exp_store = ExperienceStore()
    v_store = VectorStore()
    all_exps = []
    for status in ExperienceStatus:
        all_exps.extend(exp_store.list_by_status(status))

    to_migrate = [e for e in all_exps if e.id not in migrated_ids]
    print(f"\n=== Migrating {len(to_migrate)} experiences ===")

    for i in range(0, len(to_migrate), batch_size):
        batch = to_migrate[i:i + batch_size]
        for exp in batch:
            await backend.async_add_experience(exp)
            vec = v_store.get_vector(exp.id)
            if vec is not None:
                await backend.async_save_vector(exp.id, vec.tolist())
            migrated_ids.add(exp.id)

        checkpoint_path.write_text(json.dumps({"migrated": list(migrated_ids)}))
        print(f"Progress: {min(i + batch_size, len(to_migrate))}/{len(to_migrate)}")

    print("\n=== Post-migration check ===")
    pg_count = len(await backend.async_list_by_status(ExperienceStatus.ACTIVE))
    local_count = len(exp_store.list_by_status(ExperienceStatus.ACTIVE))
    print(f"Local active count: {local_count}")
    print(f"PG active count:    {pg_count}")
    if pg_count != local_count:
        print("WARNING: Count mismatch! Check logs and consider rollback.")
    else:
        print("Count check PASSED")

    await backend.close()
    print(f"\nMigration complete. To switch backend: export XP_BACKEND=postgres")
    print(f"To rollback: export XP_BACKEND=local  (source files preserved for 30 days)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    xp_home = Path(os.environ.get("XP_HOME", str(Path.home() / ".xp")))
    asyncio.run(migrate(args.dsn, xp_home, args.dry_run, args.batch_size))


if __name__ == "__main__":
    main()
