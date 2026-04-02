import asyncio
import os
import sys
import readline
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# 修复中文输入问题
if sys.platform == "darwin" or sys.platform.startswith("linux"):
    import locale
    locale.setlocale(locale.LC_ALL, "")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")


def _get_bus(project: str = None):
    from .container import build_command_bus
    from .project_config import ProjectManager

    if project is None:
        project = ProjectManager().get_current()

    return build_command_bus(project=project)


def _get_project() -> str:
    from .project_config import ProjectManager
    return ProjectManager().get_current()


def cmd_add(args):
    """交互式添加经验"""
    print("\n" + "=" * 60)
    print("  添加新经验")
    print("=" * 60)
    print("提示: 直接回车可跳过可选字段\n")

    # 必填字段
    task_description = input("问题/任务描述 (必填): ").strip()
    if not task_description:
        print("错误: 问题描述不能为空")
        sys.exit(1)

    solution_summary = input("解决方案摘要 (必填): ").strip()
    if not solution_summary:
        print("错误: 解决方案不能为空")
        sys.exit(1)

    key_decisions = input("关键决策/踩坑点 (可选): ").strip() or ""

    # 可选字段
    tags_input = input("技术栈标签 (逗号分隔，可选): ").strip()
    tags = [t.strip() for t in tags_input.split(",") if t.strip()] if tags_input else []

    files_input = input("相关文件路径 (逗号分隔，可选): ").strip()
    related_files = [f.strip() for f in files_input.split(",") if f.strip()] if files_input else []

    from .application.commands import ExtractExperienceCommand
    bus = _get_bus()

    exp = bus.dispatch(ExtractExperienceCommand(
        task_description=task_description,
        solution_summary=solution_summary,
        key_decisions=key_decisions,
        tags=tags,
        related_files=related_files,
    ))

    print(f"\n✓ 经验已添加 (状态: pending)")
    print(f"  ID: {exp.id}")
    print(f"  标题: {exp.title}")
    print(f"  技术栈: {', '.join(exp.metadata.tech_stack) if exp.metadata.tech_stack else '无'}")
    print(f"\n运行 `xp review` 进行审核确认")


def cmd_review(args):
    admin_key = os.environ.get("XP_ADMIN_KEY")
    if admin_key:
        user_key = os.environ.get("XP_USER_KEY", "")
        if user_key != admin_key:
            print("错误：xp review 需要 Admin 权限。请设置 XP_USER_KEY 环境变量。")
            sys.exit(1)

    from .storage import ExperienceStore, MetricsStore
    from .models import ExperienceStatus

    store = ExperienceStore()
    metrics = MetricsStore()
    pending = store.list_by_status(ExperienceStatus.PENDING)

    if not pending:
        print("没有待 review 的经验。")
        return

    print(f"\n共 {len(pending)} 条待确认经验\n{'=' * 50}")

    for i, exp in enumerate(pending, 1):
        print(f"\n[{i}/{len(pending)}] {exp.title}")
        print(f"  类型: {exp.type.value}  层级: {exp.level.value}  来源: {exp.source.value}")
        print(f"  标签: {', '.join(exp.tags) if exp.tags else '无'}")
        print(f"  ID:   {exp.id}")
        print(f"\n  问题:\n  {exp.problem[:300]}")
        print(f"\n  解决方案:\n  {exp.solution[:500]}")
        if exp.key_decisions:
            print(f"\n  关键决策/踩坑点:\n  {exp.key_decisions[:300]}")
        print(f"\n  元数据:")
        print(f"    技术栈: {', '.join(exp.metadata.tech_stack) if exp.metadata.tech_stack else '无'}")
        print(f"    场景: {', '.join(exp.metadata.scene) if exp.metadata.scene else '无'}")
        print("\n  操作: [y] 确认  [e] 编辑后确认  [n] 拒绝（原因必填）  [b] 批量确认剩余  [s] 跳过  [q] 退出")

        while True:
            choice = input("  > ").strip().lower()
            if choice == "y":
                exp.status = ExperienceStatus.ACTIVE
                exp.confidence = 0.8
                store.update(exp)
                metrics.record_review(exp.id, "confirmed")
                print("  已确认并加入知识库。")
                break
            elif choice == "e":
                import tempfile, subprocess
                with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
                    f.write(f"# {exp.title}\n\n")
                    f.write(f"**问题:**\n{exp.problem}\n\n")
                    f.write(f"**解决方案:**\n{exp.solution}\n\n")
                    f.write(f"**关键决策:**\n{exp.key_decisions}\n\n")
                    f.write(f"**标签:** {', '.join(exp.tags)}\n")
                    tmp_path_name = f.name
                editor = os.environ.get("EDITOR", "vi")
                subprocess.call([editor, tmp_path_name])
                content = open(tmp_path_name, encoding="utf-8").read()
                os.unlink(tmp_path_name)
                lines = content.splitlines()
                new_title = lines[0].lstrip("# ").strip() if lines else ""
                import asyncio as _asyncio
                from .domain.extraction import ExtractionService
                from .storage import ExperienceStore as _ExpStore, VectorStore as _VStore
                from .embeddings import get_provider as _get_provider
                _svc_store = _ExpStore()
                _exp2 = _svc_store.get(exp.id)
                if _exp2:
                    if new_title:
                        _exp2.title = new_title
                    _exp2.status = ExperienceStatus.ACTIVE
                    _exp2.confidence = 1.0
                    _svc_store.update(_exp2)
                    try:
                        _provider = _get_provider()
                        _text = f"{_exp2.title}\n{_exp2.problem}\n{_exp2.key_decisions}"
                        _vec = _provider.embed_text(_text)
                        _VStore().save_vector(_exp2.id, _vec)
                    except Exception:
                        pass
                metrics.record_review(exp.id, "confirmed")
                print("  已编辑并确认，confidence = 1.0。")
                break
            elif choice == "n":
                reason = ""
                while not reason:
                    reason = input("  拒绝原因（必填）: ").strip()
                    if not reason:
                        print("  拒绝原因不能为空，请重新输入。")
                exp.status = ExperienceStatus.ARCHIVED
                exp.reject_reason = reason
                store.update(exp)
                metrics.record_review(exp.id, "rejected", reason)
                print("  已拒绝并归档。")
                break
            elif choice == "b":
                remaining = pending[i-1:]
                for r_exp in remaining:
                    r_exp.status = ExperienceStatus.ACTIVE
                    r_exp.confidence = 0.65
                    store.update(r_exp)
                    metrics.record_review(r_exp.id, "confirmed")
                print(f"  已批量确认剩余 {len(remaining)} 条经验（confidence = 0.65）。")
                return
            elif choice == "s":
                print("  已跳过。")
                break
            elif choice == "q":
                print("\n已退出 review。")
                return
            else:
                print("  请输入 y / e / n / b / s / q")

    print("\nreview 完成。")


def cmd_import(args):
    if not args:
        print("用法: xp import <文件路径>")
        sys.exit(1)

    file_path = Path(args[0])
    if not file_path.exists():
        print(f"文件不存在: {file_path}")
        sys.exit(1)

    content = file_path.read_text(encoding="utf-8")

    from .storage import ExperienceStore, MetricsStore
    from .models import Experience, ExperienceStatus, ExperienceSource, ExperienceMetadata, ExperienceType, ExperienceLevel
    from .domain.metadata import infer_tech_stack, infer_scene, infer_type, infer_level
    import uuid
    from datetime import datetime

    def _parse_section(section: str):
        lines = section.splitlines()
        if not lines:
            return None
        title = lines[0].lstrip("#").strip()
        if not title:
            return None
        problem = ""
        solution = ""
        tags_list: list[str] = []
        current_key = None
        for line in lines[1:]:
            lower = line.lower().strip()
            if lower.startswith("**问题**") or lower.startswith("**problem**"):
                current_key = "problem"
            elif lower.startswith("**解决方案**") or lower.startswith("**solution**"):
                current_key = "solution"
            elif lower.startswith("**标签**") or lower.startswith("**tags**"):
                tag_part = line.split(":", 1)[-1].strip()
                tags_list = [t.strip() for t in tag_part.replace("，", ",").split(",") if t.strip()]
                current_key = None
            elif current_key == "problem":
                problem += line + "\n"
            elif current_key == "solution":
                solution += line + "\n"
        if not problem:
            problem = title
        if not solution:
            return None
        all_text = f"{title}\n{problem}\n{solution}"
        tech_stack = infer_tech_stack(all_text)
        scene = infer_scene(all_text)
        return Experience(
            id=str(uuid.uuid4()),
            type=infer_type(title, problem),
            level=infer_level(title, problem),
            title=title,
            tags=tags_list,
            problem=problem.strip(),
            solution=solution.strip(),
            confidence=1.0,
            status=ExperienceStatus.PENDING,
            source=ExperienceSource.MANUAL,
            created_at=datetime.utcnow().isoformat(),
            metadata=ExperienceMetadata(
                tech_stack=tech_stack if tech_stack else tags_list,
                problem_type=infer_type(title, problem).value,
                scene=scene,
            ),
        )

    store = ExperienceStore()
    imported = []
    for section in content.strip().split("\n---\n"):
        exp = _parse_section(section.strip())
        if exp:
            imported.append(store.add(exp))
    print(f"已导入 {len(imported)} 条经验（状态: pending，请运行 `xp review` 确认）")
    for exp in imported:
        print(f"  - [{exp.type.value}] {exp.title}")


def cmd_stats(args):
    since_days: Optional[int] = None
    for i, arg in enumerate(args):
        if arg == "--since" and i + 1 < len(args):
            val = args[i + 1].rstrip("d")
            try:
                since_days = int(val)
            except ValueError:
                pass

    from .application.commands import GetStatsCommand
    bus = _get_bus()
    stats = bus.dispatch(GetStatsCommand(since_days=since_days))

    period = f"最近 {since_days} 天" if since_days else "全部时间"

    print(f"\n{'=' * 50}")
    print(f"  XP 效果统计 ({period})")
    print(f"{'=' * 50}")

    w = stats["result_shown"]
    wo = stats["result_not_shown"]
    w_n = w.get("count", 0)
    wo_n = wo.get("count", 0)
    print(f"\n--- 效果对比（共 {stats['session_total']} 次会话）---")
    print(f"                    展示经验(n={w_n})  未展示经验(n={wo_n})")
    print(f"  平均对话轮数      {w['avg_iterations']:<18.1f}{wo['avg_iterations']:.1f}")
    print(f"  报错率            {w['error_rate'] * 100:<18.1f}{wo['error_rate'] * 100:.1f}%")
    print(f"  用户接受率        {w['accept_rate'] * 100:<18.1f}{wo['accept_rate'] * 100:.1f}%")
    if wo_n < 5:
        print(f"  ⚠ 未展示经验组样本量不足（{wo_n} 次），数据仅供参考")

    type_dist = stats.get("type_distribution", {})
    type_str = "  ".join(f"{k} {v}" for k, v in type_dist.items()) if type_dist else "暂无"
    print(f"\n--- 知识库状态 ---")
    print(f"  Active 经验数:     {stats['active_count']}")
    print(f"  Pending 待 review: {stats['pending_count']}")
    print(f"  Archived 归档:     {stats.get('archived_count', 0)}")
    print(f"  类型分布:          {type_str}")
    print(f"  平均置信度:        {stats.get('avg_confidence', 0):.2f}")

    print(f"\n--- 检索质量 ---")
    print(f"  检索触发次数:      {stats['search_total']}")
    print(f"  检索命中率:        {stats['search_hit_rate'] * 100:.1f}%")
    print(f"  平均返回结果数:    {stats.get('avg_result_count', 0):.1f}")
    print(f"  查询后采纳率:      {stats.get('query_adoption_rate', 0) * 100:.1f}%")
    miss_queries = stats.get("top_miss_queries", [])
    if miss_queries:
        print(f"  Top 未命中查询（近30天）:")
        for q in miss_queries[:3]:
            print('    "' + q['query'] + f'" ({q["count"]} 次)')

    print(f"\n--- 经验价值分布 ---")
    print(f"  候选确认数:        {stats['review_confirmed']}")
    print(f"  候选拒绝数:        {stats['review_rejected']}")
    print(f"  候选通过率:        {stats['review_pass_rate'] * 100:.1f}%")
    top_adopted = stats.get("top_adopted_experiences", [])
    if top_adopted:
        print(f"  高采纳率 TOP {len(top_adopted)}:")
        for exp_stat in top_adopted:
            short_id = exp_stat["experience_id"][:8]
            title = exp_stat.get("title", short_id)
            print(f"    [{short_id}] {title}  采纳率 {exp_stat['adoption_rate'] * 100:.0f}%")
    zombie = stats.get("zombie_count", 0)
    if zombie:
        print(f"  僵尸经验（从未命中）: {zombie} 条")

    trend = stats.get("trend_30d", {})
    if trend:
        print(f"\n--- 时间趋势（近 30 天）---")
        print(f"  新增经验:          +{trend.get('new_experiences', 0)} 条")
        print(f"  新增会话:          +{trend.get('new_sessions', 0)} 次")

    if stats["session_total"] < 10:
        print(f"\n  注意: 当前会话数较少（{stats['session_total']} 次），对比数据仅供参考。")
    print()


def cmd_analyze(args):
    from .application.commands import AnalyzeQualityCommand
    bus = _get_bus()
    report = bus.dispatch(AnalyzeQualityCommand())

    print(f"\n{'=' * 60}")
    print(f"  XP 经验质量分析报告")
    print(f"{'=' * 60}")

    print(f"\n--- 知识库概览 ---")
    summary = report["summary"]
    print(f"  经验总数:      {summary['total_experiences']}")
    print(f"  Pending 待审:  {summary['pending_count']}")
    print(f"  Active 有效:   {summary['active_count']}")
    print(f"  Archived 归档: {summary['archived_count']}")

    print(f"\n--- 反馈统计 ---")
    fb = report["feedback_stats"]
    print(f"  总反馈数:      {fb['total_feedback']}")
    print(f"  采纳数:        {fb['adopted_count']}")
    print(f"  整体采纳率:    {fb['adoption_rate'] * 100:.1f}%")

    print(f"\n--- 低采纳率经验 ---")
    low = report["low_adoption_experiences"]
    if low["count"] > 0:
        print(f"  共 {low['count']} 条经验采纳率 < 30%")
        print(f"  经验 ID: {', '.join(low['ids'][:5])}")
        if len(low["ids"]) > 5:
            print(f"  ... 等共 {low['count']} 条")
    else:
        print("  暂无低采纳率经验")

    print(f"\n--- 反馈拒绝原因 TOP ---")
    if report["reject_reasons"]:
        for reason, cnt in sorted(report["reject_reasons"].items(), key=lambda x: -x[1])[:5]:
            print(f"  {reason}: {cnt} 次")
    else:
        print("  暂无拒绝原因记录")

    print(f"\n--- 发现的问题模式 ---")
    if report["low_quality_patterns"]:
        for i, pattern in enumerate(report["low_quality_patterns"], 1):
            print(f"\n  [{i}] {pattern['type']}")
            print(f"      问题: {pattern['issue']}")
            print(f"      建议: {pattern['suggestion']}")
            print(f"      数据: {pattern['data']}")
            actions = pattern.get("actions", [])
            if actions:
                print(f"      操作:")
                for action in actions:
                    print(f"        {action}")
    else:
        print("  未发现明显的质量问题")

    all_actions = []
    for p in report["low_quality_patterns"]:
        all_actions.extend(p.get("actions", []))
    if all_actions:
        print(f"\n--- 下一步操作汇总（可直接复制执行）---")
        seen: set[str] = set()
        for action in all_actions:
            cmd = action.split("#")[0].strip()
            if cmd not in seen:
                print(f"  {action}")
                seen.add(cmd)

    print(f"\n--- 优化建议 ---")
    for rec in report["recommendations"]:
        if rec:
            print(f"  • {rec}")

    print(f"\n{'=' * 60}\n")


def cmd_show(args):
    if not args:
        print("用法: xp show <经验ID前缀>")
        sys.exit(1)
    prefix = args[0]
    from .storage import ExperienceStore
    from .models import ExperienceStatus
    store = ExperienceStore()
    all_exps = []
    for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
        all_exps.extend(store.list_by_status(status))
    matches = [e for e in all_exps if e.id.startswith(prefix)]
    if len(matches) == 0:
        print(f"未找到匹配 '{prefix}' 的经验")
        sys.exit(1)
    if len(matches) > 1:
        print(f"匹配到 {len(matches)} 条经验，请提供更长的前缀：")
        for e in matches:
            print(f"  {e.id[:8]}  {e.status.value:8}  {e.title}")
        sys.exit(1)
    exp = matches[0]
    print(f"\n{'=' * 60}")
    print(f"  {exp.title}")
    print(f"{'=' * 60}")
    print(f"  ID:     {exp.id}")
    print(f"  状态:   {exp.status.value}")
    print(f"  类型:   {exp.type.value}  层级: {exp.level.value}")
    print(f"  标签:   {', '.join(exp.tags) if exp.tags else '无'}")
    print(f"  技术栈: {', '.join(exp.metadata.tech_stack) if exp.metadata.tech_stack else '无'}")
    print(f"  创建于: {exp.created_at}")
    print(f"  最近命中: {exp.last_hit_at or '从未'}")
    print(f"\n  问题:\n  {exp.problem}")
    print(f"\n  解决方案:\n  {exp.solution}")
    if exp.metadata.scene:
        print(f"\n  场景: {', '.join(exp.metadata.scene)}")
    if exp.related_files:
        print(f"  相关文件: {', '.join(exp.related_files)}")
    print(f"\n{'=' * 60}\n")


def cmd_edit(args):
    if not args:
        print("用法: xp edit <经验ID前缀>")
        sys.exit(1)
    prefix = args[0]
    from .storage import ExperienceStore
    store = ExperienceStore()
    all_exps = []
    from .models import ExperienceStatus
    for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
        all_exps.extend(store.list_by_status(status))
    matches = [e for e in all_exps if e.id.startswith(prefix)]
    if len(matches) != 1:
        print(f"未找到匹配 '{prefix}' 的经验（或匹配到多条，请提供更长的前缀）")
        sys.exit(1)
    exp = matches[0]

    print(f"\n{'=' * 60}")
    print(f"  编辑经验: {exp.title}")
    print(f"  ID: {exp.id}")
    print(f"{'=' * 60}")
    print("提示: 直接回车保留原值\n")

    try:
        new_title = input(f"标题 [{exp.title}]: ").strip()
        if new_title:
            exp.title = new_title

        print(f"问题描述 (当前): {exp.problem[:200]}")
        new_problem = input("新问题描述 (回车保留): ").strip()
        if new_problem:
            exp.problem = new_problem

        print(f"解决方案 (当前): {exp.solution[:200]}")
        new_solution = input("新解决方案 (回车保留): ").strip()
        if new_solution:
            exp.solution = new_solution

        tags_str = ", ".join(exp.tags)
        new_tags_input = input(f"标签 [{tags_str}]: ").strip()
        if new_tags_input:
            exp.tags = [t.strip() for t in new_tags_input.split(",") if t.strip()]

        if exp.status == ExperienceStatus.ARCHIVED:
            reactivate = input("是否重新激活为 Active? [y/N]: ").strip().lower()
            if reactivate == "y":
                exp.status = ExperienceStatus.ACTIVE
    except KeyboardInterrupt:
        print("\n已取消编辑")
        return

    store.update(exp)
    print(f"\n已保存: [{exp.id[:8]}] {exp.title}  (状态: {exp.status.value})")


def cmd_archive(args):
    if not args:
        print("用法: xp archive <经验ID前缀>")
        sys.exit(1)
    prefix = args[0]
    from .application.commands import ArchiveExperienceCommand, DeleteExperienceCommand
    from .storage import ExperienceStore
    from .models import ExperienceStatus
    store = ExperienceStore()
    all_exps = []
    for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
        all_exps.extend(store.list_by_status(status))
    matches = [e for e in all_exps if e.id.startswith(prefix)]
    if len(matches) != 1:
        print(f"未找到匹配 '{prefix}' 的经验（或匹配到多条，请提供更长的前缀）")
        sys.exit(1)
    exp = matches[0]
    exp.status = ExperienceStatus.ARCHIVED
    store.update(exp)
    print(f"已归档: [{exp.id[:8]}] {exp.title}")


def cmd_delete(args):
    if not args:
        print("用法: xp delete <经验ID前缀>")
        sys.exit(1)
    prefix = args[0]
    from .application.commands import DeleteExperienceCommand
    bus = _get_bus()
    exp_id = bus.dispatch(DeleteExperienceCommand(prefix=prefix))
    if exp_id is None:
        print(f"未找到匹配 '{prefix}' 的经验（或匹配到多条，请提供更长的前缀）")
        sys.exit(1)
    print(f"已删除: {exp_id[:8]}")


def cmd_init(args):
    """初始化项目"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", "-p", required=True, help="项目名称")
    parser.add_argument("--tags", "-t", help="技术栈标签，逗号分隔")
    parser.add_argument("--root", "-r", help="项目根目录路径")
    parsed = parser.parse_args(args)

    tags = [t.strip() for t in parsed.tags.split(",") if t.strip()] if parsed.tags else []

    from .project_config import ProjectManager
    pm = ProjectManager()
    try:
        config = pm.create(parsed.project, tags, parsed.root)
        pm.set_current(parsed.project)
        print(f"\n项目 '{parsed.project}' 创建成功！")
        print(f"  技术栈: {', '.join(config.tags) if config.tags else '无'}")
        print(f"  根目录: {config.root_path or '未设置'}")
        print(f"\n当前已切换到项目 '{parsed.project}'")
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)


def cmd_project(args):
    from .project_config import ProjectManager
    pm = ProjectManager()

    if not args:
        current = pm.get_current()
        print(f"\n当前项目: {current}")
        config = pm.get(current)
        if config:
            print(f"  技术栈: {', '.join(config.tags) if config.tags else '无'}")
            print(f"  云端同步: {'已启用' if config.cloud_sync_enabled else '未启用'}")
        return

    if args[0] == "list":
        projects = pm.list()
        current = pm.get_current()
        print(f"\n项目列表:")
        for p in projects:
            marker = " *" if p.name == current else ""
            print(f"  {p.name}{marker}")
            print(f"    标签: {', '.join(p.tags) if p.tags else '无'}")
    elif args[0] == "switch" and len(args) > 1:
        all_names = [p.name for p in pm.list()]
        if args[1] in all_names:
            pm.set_current(args[1])
            print(f"已切换到项目 '{args[1]}'")
        else:
            print(f"项目 '{args[1]}' 不存在")
            sys.exit(1)
    else:
        print("用法: xp project [list|switch <name>]")


def cmd_watch(args):
    from .storage import ExperienceStore, MetricsStore
    from .file_watcher import FileWatcher, TTLManager, calculate_files_hashes
    from .models import ExperienceStatus
    from .project_config import ProjectManager

    project = ProjectManager().get_current()
    store = ExperienceStore()
    file_watcher = FileWatcher()
    ttl_manager = TTLManager()

    all_active = store.list_active()
    project_exps = [e for e in all_active if e.project == project]

    stale_list = file_watcher.run_check(project_exps)
    for exp, changed_files in stale_list:
        exp.stale_reason = f"Files changed: {', '.join(changed_files)}"
        store.update(exp)

    expired = ttl_manager.check_experiences(project_exps)
    for exp in expired:
        exp.status = ExperienceStatus.ARCHIVED
        exp.reject_reason = "TTL expired (90 days no hit)"
        store.update(exp)

    print(f"\n{'=' * 60}")
    print(f"  XP 失效检测报告")
    print(f"{'=' * 60}")

    print(f"\n--- 文件变更检测 ---")
    if stale_list:
        print(f"  发现 {len(stale_list)} 条经验相关文件已变更:")
        for exp, files in stale_list:
            print(f"\n  [{exp.title}]")
            print(f"    ID: {exp.id}")
            print(f"    变更文件: {', '.join(files)}")
    else:
        print("  未发现文件变更")

    print(f"\n--- TTL 过期检查 ---")
    if expired:
        print(f"  {len(expired)} 条经验已归档（90天未使用）:")
        for exp in expired:
            print(f"    - {exp.title}")
    else:
        print("  无过期经验")

    print(f"\n{'=' * 60}\n")


def cmd_sync(args):
    print("云端同步已移除。请使用 REST API 进行团队共享。")


def cmd_migrate(args):
    force = "--force" in args

    async def run():
        from .project_config import ProjectManager
        from .storage import ExperienceStore, MetricsStore
        from .embeddings import get_provider
        from .storage import VectorStore
        from .models import ExperienceStatus

        store = ExperienceStore()
        provider = get_provider()
        v_store = VectorStore()

        all_exps = []
        for status in [ExperienceStatus.PENDING, ExperienceStatus.ACTIVE, ExperienceStatus.ARCHIVED]:
            all_exps.extend(store.list_by_status(status))

        print(f"总经验数量: {len(all_exps)}")

        if force:
            missing_exps = all_exps
            print(f"--force 模式：全量重新生成 {len(missing_exps)} 条经验的向量")
        else:
            ids, _ = v_store.get_all_vectors()
            missing_exps = [e for e in all_exps if e.id not in ids]

        if not missing_exps:
            print("所有经验均已生成向量，无需迁移。")
            return

        print(f"发现 {len(missing_exps)} 条缺失向量的经验，开始生成...")
        batch_size = 50
        for i in range(0, len(missing_exps), batch_size):
            batch = missing_exps[i:i+batch_size]
            texts = [f"{e.title}\n{e.problem}\n{e.key_decisions}" for e in batch]
            vecs = provider.embed_texts(texts)
            v_store.save_vectors(list(zip([e.id for e in batch], vecs)))
            print(f"进度: {min(i+batch_size, len(missing_exps))}/{len(missing_exps)}")

        print("迁移完成。")

    asyncio.run(run())

def main():
    args = sys.argv[1:]
    if not args:
        print("用法: xp <命令> [参数]")
        print("  xp add                 交互式添加新经验")
        print("  xp review              review 待确认的经验")
        print("  xp import <文件>       从 Markdown 文件导入种子经验")
        print("  xp stats               查看效果统计")
        print("  xp stats --since 7d    查看最近 7 天统计")
        print("  xp analyze             分析经验质量报告")
        print("  xp init --project <n>  初始化新项目")
        print("  xp project [list|switch] 项目管理")
        print("  xp watch               检查文件变更和过期经验")
        print("  xp sync [up|down]      云端同步")
        print("  xp migrate             为旧数据生成缺失的向量")
        return

    cmd = args[0]
    rest = args[1:]

    if cmd == "add":
        cmd_add(rest)
    elif cmd == "migrate":
        cmd_migrate(rest)
    elif cmd == "review":
        cmd_review(rest)
    elif cmd == "import":
        cmd_import(rest)
    elif cmd == "stats":
        cmd_stats(rest)
    elif cmd == "analyze":
        cmd_analyze(rest)
    elif cmd == "show":
        cmd_show(rest)
    elif cmd == "edit":
        cmd_edit(rest)
    elif cmd == "archive":
        cmd_archive(rest)
    elif cmd == "delete":
        cmd_delete(rest)
    elif cmd == "init":
        cmd_init(rest)
    elif cmd == "project":
        cmd_project(rest)
    elif cmd == "watch":
        cmd_watch(rest)
    elif cmd == "sync":
        cmd_sync(rest)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
