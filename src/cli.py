import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _get_service():
    from .knowledge import KnowledgeService
    from .storage import ExperienceStore, MetricsStore

    return KnowledgeService(ExperienceStore(), MetricsStore())


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


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: xp <命令> [参数]")
        print("  xp review              review 待确认的经验")
        print("  xp import <文件>       从 Markdown 文件导入种子经验")
        print("  xp stats               查看效果统计")
        print("  xp stats --since 7d    查看最近 7 天统计")
        print("  xp analyze             分析经验质量报告")
        return

    cmd = args[0]
    rest = args[1:]

    if cmd == "review":
        cmd_review(rest)
    elif cmd == "import":
        cmd_import(rest)
    elif cmd == "stats":
        cmd_stats(rest)
    elif cmd == "analyze":
        cmd_analyze(rest)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
