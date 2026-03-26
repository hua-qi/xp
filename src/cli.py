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


def _get_service(project: str = None):
    from .knowledge import KnowledgeService
    from .project_config import ProjectManager
    from .storage import ExperienceStore, MetricsStore

    if project is None:
        # 获取当前项目
        project = ProjectManager().get_current()

    return KnowledgeService(ExperienceStore(), MetricsStore(), project)


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

    service = _get_service()

    async def run():
        exp = await service.extract_experience(
            task_description=task_description,
            solution_summary=solution_summary,
            key_decisions=key_decisions,
            tags=tags,
            related_files=related_files,
        )
        return exp

    exp = asyncio.run(run())

    print(f"\n✓ 经验已添加 (状态: pending)")
    print(f"  ID: {exp.id}")
    print(f"  标题: {exp.title}")
    print(f"  技术栈: {', '.join(exp.metadata.tech_stack) if exp.metadata.tech_stack else '无'}")
    print(f"\n运行 `xp review` 进行审核确认")


def cmd_review(args):
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
        print(f"\n  元数据:")
        print(f"    技术栈: {', '.join(exp.metadata.tech_stack) if exp.metadata.tech_stack else '无'}")
        print(f"    场景: {', '.join(exp.metadata.scene) if exp.metadata.scene else '无'}")
        print(f"    关键词: {', '.join(exp.metadata.keywords[:10])}..." if len(exp.metadata.keywords) > 10 else f"    关键词: {', '.join(exp.metadata.keywords)}")
        print("\n  操作: [y] 确认  [n] 拒绝  [s] 跳过  [q] 退出")

        while True:
            choice = input("  > ").strip().lower()
            if choice == "y":
                exp.status = ExperienceStatus.ACTIVE
                exp.confidence = 0.8
                store.update(exp)
                metrics.record_review(exp.id, "confirmed")
                print("  已确认并加入知识库。")
                break
            elif choice == "n":
                reason = input("  拒绝原因（可直接回车跳过）: ").strip() or None
                exp.status = ExperienceStatus.ARCHIVED
                exp.reject_reason = reason
                store.update(exp)
                metrics.record_review(exp.id, "rejected", reason)
                print("  已拒绝并归档。")
                break
            elif choice == "s":
                print("  已跳过。")
                break
            elif choice == "q":
                print("\n已退出 review。")
                return
            else:
                print("  请输入 y / n / s / q")

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
    service = _get_service()

    async def run():
        imported = await service.import_from_markdown(content)
        return imported

    imported = asyncio.run(run())
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

    service = _get_service()
    stats = service.get_stats(since_days)

    period = f"最近 {since_days} 天" if since_days else "全部时间"

    print(f"\n{'=' * 50}")
    print(f"  XP 效果统计 ({period})")
    print(f"{'=' * 50}")
    print(f"\n--- 知识库状态 ---")
    print(f"  Active 经验数:     {stats['active_count']}")
    print(f"  Pending 待 review: {stats['pending_count']}")

    print(f"\n--- 过程指标 ---")
    print(f"  检索触发次数:   {stats['search_total']}")
    print(f"  检索命中率:     {stats['search_hit_rate'] * 100:.1f}%")
    print(f"  候选确认数:     {stats['review_confirmed']}")
    print(f"  候选拒绝数:     {stats['review_rejected']}")
    print(f"  候选通过率:     {stats['review_pass_rate'] * 100:.1f}%")

    print(f"\n--- 效果对比 (共 {stats['session_total']} 次会话) ---")
    w = stats["with_injection"]
    wo = stats["without_injection"]
    print(f"                    有经验注入    无注入")
    print(f"  平均对话轮数      {w['avg_iterations']:<14.1f}{wo['avg_iterations']:.1f}")
    print(f"  报错率            {w['error_rate'] * 100:<14.1f}{wo['error_rate'] * 100:.1f}%")
    print(f"  用户接受率        {w['accept_rate'] * 100:<14.1f}{wo['accept_rate'] * 100:.1f}%")

    if stats["session_total"] < 10:
        print(f"\n  注意: 当前会话数较少（{stats['session_total']} 次），对比数据仅供参考，建议积累 30 次以上后再做判断。")
    print()


def cmd_analyze(args):
    service = _get_service()

    async def run():
        report = await service.analyze_quality()
        return report

    report = asyncio.run(run())

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
    else:
        print("  未发现明显的质量问题")

    print(f"\n--- 优化建议 ---")
    for rec in report["recommendations"]:
        if rec:
            print(f"  • {rec}")

    print(f"\n{'=' * 60}\n")


def cmd_init(args):
    """初始化项目"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", "-p", required=True, help="项目名称")
    parser.add_argument("--tags", "-t", help="技术栈标签，逗号分隔")
    parser.add_argument("--root", "-r", help="项目根目录路径")
    parsed = parser.parse_args(args)

    tags = [t.strip() for t in parsed.tags.split(",") if t.strip()] if parsed.tags else []

    service = _get_service()
    try:
        config = service.create_project(parsed.project, tags, parsed.root)
        service.switch_project(parsed.project)
        print(f"\n项目 '{parsed.project}' 创建成功！")
        print(f"  技术栈: {', '.join(config.tags) if config.tags else '无'}")
        print(f"  根目录: {config.root_path or '未设置'}")
        print(f"\n当前已切换到项目 '{parsed.project}'")
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)


def cmd_project(args):
    """项目管理"""
    service = _get_service()

    if not args:
        # 显示当前项目
        current = service.current_project
        print(f"\n当前项目: {current}")
        config = service.get_current_project_config()
        if config:
            print(f"  技术栈: {', '.join(config.tags) if config.tags else '无'}")
            print(f"  云端同步: {'已启用' if config.cloud_sync_enabled else '未启用'}")
        return

    if args[0] == "list":
        projects = service.list_projects()
        current = service.current_project
        print(f"\n项目列表:")
        for p in projects:
            marker = " *" if p.name == current else ""
            print(f"  {p.name}{marker}")
            print(f"    标签: {', '.join(p.tags) if p.tags else '无'}")
    elif args[0] == "switch" and len(args) > 1:
        if service.switch_project(args[1]):
            print(f"已切换到项目 '{args[1]}'")
        else:
            print(f"项目 '{args[1]}' 不存在")
            sys.exit(1)
    else:
        print("用法: xp project [list|switch <name>]")


def cmd_watch(args):
    """文件监听和失效检测"""
    service = _get_service()

    async def run():
        # 检查失效经验
        stale_list = await service.check_stale_experiences()

        # 运行 TTL 检查
        expired = await service.run_ttl_check()

        return stale_list, expired

    stale_list, expired = asyncio.run(run())

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
    """云端同步"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("direction", choices=["up", "down"], help="同步方向")
    parser.add_argument("--provider", choices=["supabase", "weaviate", "elasticsearch"], help="云端Provider")
    parsed = parser.parse_args(args)

    service = _get_service()
    config = service.get_current_project_config()

    async def run():
        if parsed.provider:
            # 启用云端同步
            print(f"正在连接到 {parsed.provider}...")
            # 这里需要从配置或交互式输入获取连接参数
            print("请先在项目配置中设置云端同步参数")
            return

        if parsed.direction == "up":
            print("正在同步到云端...")
            result = await service.sync_to_cloud()
            if "error" in result:
                print(f"错误: {result['error']}")
            else:
                print(f"同步完成: {result.get('success', 0)} 成功, {result.get('failed', 0)} 失败")
        else:
            print("正在从云端同步...")
            result = await service.sync_from_cloud()
            if "error" in result:
                print(f"错误: {result['error']}")
            else:
                print(f"同步完成: {result.get('new', 0)} 新增, {result.get('merged', 0)} 更新")

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
        return

    cmd = args[0]
    rest = args[1:]

    if cmd == "add":
        cmd_add(rest)
    elif cmd == "review":
        cmd_review(rest)
    elif cmd == "import":
        cmd_import(rest)
    elif cmd == "stats":
        cmd_stats(rest)
    elif cmd == "analyze":
        cmd_analyze(rest)
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
