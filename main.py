from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm

from checker import check_all_contracts
from exporter import (
    export_all,
    export_by_agent,
    export_contract_summary,
    export_expiring_list,
    export_pending_list,
    export_review_progress,
    export_review_progress_detail,
    filter_contracts,
    follow_up_action_label,
    get_contract_summary,
    get_expiring_contracts,
    get_pending_items,
    issue_status_label,
    issue_type_label,
    payment_method_label,
    priority_label,
    change_risk_label,
    risk_level_label,
    sort_contracts,
)
from models import Contract, FollowUpAction, IssueType, RiskLevel, IssueStatus, RuleConfig, PriorityLevel, ChangeRiskLevel
from scanner import scan_folder
from storage import (
    add_batch,
    get_batches,
    get_contracts_by_batch,
    load_contracts,
    load_rule,
    save_contracts,
    save_rule,
    update_contract,
    update_contracts,
)


console = Console()


def risk_color(level: RiskLevel) -> str:
    return {RiskLevel.LOW: "green", RiskLevel.MEDIUM: "yellow", RiskLevel.HIGH: "red"}.get(
        level, "white"
    )


def status_color(status: IssueStatus) -> str:
    return {
        IssueStatus.PENDING: "yellow",
        IssueStatus.CONFIRMED: "blue",
        IssueStatus.RESOLVED: "green",
        IssueStatus.IGNORED: "dim",
    }.get(status, "white")


def display_contract_card(c: Contract, show_issues: bool = True, show_status: bool = True) -> None:
    from rich.console import Group

    color = risk_color(c.risk_level)
    elements = []

    line1 = Text()
    line1.append("● ", style=color)
    line1.append("风险等级: ")
    line1.append(risk_level_label(c.risk_level), style=f"bold {color}")
    elements.append(line1)

    elements.append(Text(f"🏠 房号: {c.room_number or '未识别'}"))
    line2 = Text(f"👤 租客: {c.tenant_name or '未识别'} | 身份证: ")
    if c.tenant_id_number:
        line2.append(c.tenant_id_number)
    else:
        line2.append("缺失", style="dim")
    elements.append(line2)

    elements.append(Text(f"📅 租期: {c.start_date or '?'} ~ {c.end_date or '?'}"))
    elements.append(Text(f"💰 月租金: {c.monthly_rent:.0f}元 | 押金: {c.deposit:.0f}元 | 付款: {payment_method_label(c.payment_method)}"))
    line3 = Text("🤝 经纪人: ")
    if c.agent_name:
        line3.append(c.agent_name)
    else:
        line3.append("未指定", style="dim")
    elements.append(line3)

    sig_line = Text("✍️  签名: ")
    sig_line.append(f"租客:{'✅' if c.has_tenant_signature else '❌'}  ")
    sig_line.append(f"房东:{'✅' if c.has_landlord_signature else '❌'}  ")
    sig_line.append(f"经纪人:{'✅' if c.has_agent_signature else '❌'}")
    elements.append(sig_line)

    if c.pending_issues_count > 0 or c.resolved_issues_count > 0:
        status_line = Text("📋 处理进度: ")
        status_line.append(f"待处理 {c.pending_issues_count}", style="yellow")
        status_line.append(" | ")
        status_line.append(f"已处理 {c.resolved_issues_count}", style="green")
        status_line.append(f" / 共 {len(c.issues)}")
        elements.append(status_line)

    if show_issues and c.issues:
        elements.append(Text(""))
        elements.append(Text("⚠️  问题列表:", style="bold red"))
        for idx, issue in enumerate(c.issues, 1):
            ic = risk_color(issue.risk_level)
            sc = status_color(issue.status)
            issue_line = Text(f"   [{idx}] ")
            issue_line.append("● ", style=ic)
            issue_line.append(f"[{issue_type_label(issue.issue_type)}] ")
            issue_line.append(issue.description)
            if show_status:
                issue_line.append(f" ({issue_status_label(issue.status)})", style=sc)
            elements.append(issue_line)
            if issue.suggestion:
                elements.append(Text(f"      💡 建议: {issue.suggestion}", style="dim"))
            if issue.review_note:
                elements.append(Text(f"      📝 备注: {issue.review_note}", style="blue dim"))
            if issue.latest_follow_up:
                fu = issue.latest_follow_up
                fu_info = f"      📞 跟进: {follow_up_action_label(fu.action)} - {fu.content}"
                if fu.operator:
                    fu_info += f" ({fu.operator})"
                elements.append(Text(fu_info, style="cyan dim"))

    if c.field_changes:
        elements.append(Text(""))
        elements.append(Text("🔄 字段变更历史:", style="bold magenta"))
        for fc in c.field_changes[-5:]:
            ct = fc.change_time[:16].replace("T", " ")
            line = Text(f"   [{ct}] {fc.field_name}: {fc.old_value} → {fc.new_value}", style="magenta dim")
            if fc.change_risk and fc.change_risk != ChangeRiskLevel.NONE:
                r_color = {
                    ChangeRiskLevel.LOW: "blue",
                    ChangeRiskLevel.MEDIUM: "yellow",
                    ChangeRiskLevel.HIGH: "red",
                }.get(fc.change_risk, "dim")
                line.append(f" ⚠️[{change_risk_label(fc.change_risk)}风险]", style=f"bold {r_color}")
                if fc.risk_note:
                    line.append(f" {fc.risk_note}", style=r_color)
            elements.append(line)
        if len(c.field_changes) > 5:
            elements.append(Text(f"   ... 还有 {len(c.field_changes)-5} 条变更", style="dim"))

    if c.high_risk_changes:
        elements.append(Text(""))
        hr_line = Text("🚨 高风险变更: ", style="bold red")
        hr_line.append(f"{len(c.high_risk_changes)} 条", style="bold red")
        elements.append(hr_line)
        for fc in c.high_risk_changes[-3:]:
            elements.append(Text(f"   • {fc.field_name}: {fc.old_value} → {fc.new_value} - {fc.risk_note}", style="red dim"))

    latest = c.latest_follow_up
    if latest:
        fu_info = f"📞 最近跟进: {follow_up_action_label(latest.action)} - {latest.content}"
        if latest.operator:
            fu_info += f" (负责人: {latest.operator})"
        elements.append(Text(""))
        elements.append(Text(fu_info, style="bold cyan"))

    title = Text(Path(c.file_path).name, style="bold")
    console.print(Panel(Group(*elements), title=title, border_style=color))


@click.group(help="租房合同审核工具 - 面向小型中介批量整理合同")
@click.option("--data-dir", type=click.Path(), default=".", help="数据存储目录")
@click.pass_context
def cli(ctx, data_dir):
    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = data_dir


@cli.command(help="扫描文件夹内的合同文本并识别关键信息")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--recursive/--no-recursive", "-r", default=False, help="递归扫描子文件夹")
@click.option("--incremental/--full-scan", default=True, help="增量扫描(默认)/全量扫描")
@click.option("--auto-check/--no-auto-check", default=True, help="扫描后自动执行检查")
@click.option("--verbose/--no-verbose", "-v", default=False, help="显示详细识别结果")
@click.option("--rule-file", type=click.Path(), help="使用指定的规则配置文件")
@click.pass_context
def scan(ctx, folder, recursive, incremental, auto_check, verbose, rule_file):
    data_dir = ctx.obj["data_dir"]
    console.print(f"[bold blue]🔍 正在扫描文件夹:[/bold blue] {folder}")
    console.print(f"   模式: {'递归' if recursive else '单层'} | {'增量' if incremental else '全量'}扫描")

    rule = load_rule(data_dir)
    if rule_file and os.path.exists(rule_file):
        import json
        with open(rule_file, "r", encoding="utf-8") as f:
            rule_data = json.load(f)
        rule = RuleConfig.model_validate(rule_data)
        console.print(f"   使用规则: {rule.rule_name} (来自文件)")
    else:
        console.print(f"   使用规则: {rule.get_display_name()}")

    existing = load_contracts(data_dir) if incremental else []
    scan_result = scan_folder(
        folder,
        recursive=recursive,
        existing_contracts=existing,
        incremental=incremental,
    )

    contracts = scan_result.all_contracts

    if auto_check and contracts:
        contracts = check_all_contracts(contracts, rule)
        console.print(f"   规则检查完成")

    batch_id = add_batch(scan_result, folder, rule, data_dir)

    console.print(f"\n[bold green]✅ 扫描完成[/bold green] 批次: {batch_id}")
    console.print(f"   总计: {scan_result.total_count} 份合同")
    console.print(f"   [green]新增: {scan_result.new_count}[/green] | "
                  f"[yellow]更新: {scan_result.updated_count}[/yellow] | "
                  f"[dim]未变化: {scan_result.unchanged_count}[/dim]")

    if scan_result.errors:
        console.print(f"   [red]错误: {len(scan_result.errors)} 个文件[/red]")

    if auto_check and contracts:
        high = sum(1 for c in contracts if c.risk_level == RiskLevel.HIGH)
        medium = sum(1 for c in contracts if c.risk_level == RiskLevel.MEDIUM)
        low = sum(1 for c in contracts if c.risk_level == RiskLevel.LOW)
        console.print(f"\n   风险分布: [red]高风险 {high}[/red], "
                      f"[yellow]中风险 {medium}[/yellow], "
                      f"[green]低风险/正常 {low}[/green]")

    if verbose and contracts:
        console.print("")
        for c in contracts:
            display_contract_card(c, show_issues=auto_check)


@cli.command("check", help="按规则检查合同问题")
@click.option("--high-risk-only", is_flag=True, help="只显示高风险合同")
@click.option("--sort-by", type=click.Choice(["risk", "end_date", "room", "rent"]), default="risk", help="排序方式")
@click.option("--rule-file", type=click.Path(), help="使用指定的规则配置文件")
@click.option("--show-rule", is_flag=True, help="显示当前使用的规则配置")
@click.option("--change-risk", is_flag=True, help="只显示有高风险变更的合同")
@click.pass_context
def check_cmd(ctx, high_risk_only, sort_by, rule_file, show_rule, change_risk):
    data_dir = ctx.obj["data_dir"]
    contracts = load_contracts(data_dir)

    if not contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    rule = load_rule(data_dir)
    if rule_file and os.path.exists(rule_file):
        import json
        with open(rule_file, "r", encoding="utf-8") as f:
            rule_data = json.load(f)
        rule = RuleConfig.model_validate(rule_data)

    console.print(f"📋 当前规则: [bold]{rule.get_display_name()}[/bold] ({rule.rule_name})")

    if show_rule:
        console.print(f"   租金异常阈值: ±{rule.rent_deviation_threshold*100:.0f}%")
        console.print(f"   押金倍数: {', '.join(str(r) for r in rule.deposit_multiples)}")
        console.print(f"   经纪人签名检查: {'开启' if rule.require_agent_signature else '关闭'}")
        console.print(f"   高风险类型: {', '.join(issue_type_label(t) for t in rule.high_risk_issue_types)}")
        console.print("")

    contracts = check_all_contracts(contracts, rule)
    save_contracts(contracts, data_dir)

    if high_risk_only:
        contracts = [c for c in contracts if c.risk_level == RiskLevel.HIGH]
        if not contracts:
            console.print("[bold green]🎉 没有高风险合同![/bold green]")
            return

    if change_risk:
        contracts = [c for c in contracts if c.high_risk_changes]
        if not contracts:
            console.print("[bold green]🎉 没有高风险变更的合同![/bold green]")
            return

    contracts = sort_contracts(contracts, sort_by)

    high = sum(1 for c in contracts if c.risk_level == RiskLevel.HIGH)
    medium = sum(1 for c in contracts if c.risk_level == RiskLevel.MEDIUM)
    low = sum(1 for c in contracts if c.risk_level == RiskLevel.LOW)
    hr_change = sum(1 for c in contracts if c.high_risk_changes)
    stats = [
        f"[red]高风险 {high}[/red]",
        f"[yellow]中风险 {medium}[/yellow]",
        f"[green]低/无 {low}[/green]",
    ]
    if hr_change > 0:
        stats.append(f"[bold red]高风险变更 {hr_change}[/bold red]")
    console.print(f"\n[bold]共 {len(contracts)} 份合同: [/bold]{', '.join(stats)}\n")

    for c in contracts:
        display_contract_card(c)


@cli.command("list", help="列出合同，支持多种筛选条件")
@click.option("--room", help="按房源/房号筛选(支持模糊匹配)")
@click.option("--expire-month", help="按到期月份筛选，格式 YYYY-MM (如 2025-06)")
@click.option("--agent", help="按经纪人筛选")
@click.option("--issue-type", type=click.Choice([
    "missing_signature", "date_conflict", "lease_overlap",
    "abnormal_rent", "deposit_mismatch", "invalid_id_number"
]), help="按异常类型筛选")
@click.option("--high-risk-only", is_flag=True, help="只显示高风险合同")
@click.option("--batch-id", help="按扫描批次筛选")
@click.option("--start-date", help="租期开始日期(YYYY-MM-DD)起")
@click.option("--end-date", help="租期结束日期(YYYY-MM-DD)止")
@click.option("--sort-by", type=click.Choice(["risk", "end_date", "room", "rent"]), default="end_date", help="排序方式")
@click.option("--batches", is_flag=True, help="列出所有扫描批次")
@click.option("--overdue", "follow_overdue", is_flag=True, help="只显示有逾期跟进任务的合同")
@click.option("--due-today", "follow_due_today", is_flag=True, help="只显示今日到期跟进的合同")
@click.option("--follow-operator", help="按跟进负责人筛选")
@click.option("--follow-priority", type=click.Choice(["low", "medium", "high", "urgent"]),
              help="按跟进优先级筛选")
@click.option("--follow-summary", is_flag=True, help="按负责人汇总展示跟进任务")
@click.option("--change-risk", is_flag=True, help="只显示有高风险变更的合同")
@click.pass_context
def list_cmd(ctx, room, expire_month, agent, issue_type, high_risk_only,
             batch_id, start_date, end_date, sort_by, batches,
             follow_overdue, follow_due_today, follow_operator,
             follow_priority, follow_summary, change_risk):
    data_dir = ctx.obj["data_dir"]

    if batches:
        batch_list = get_batches(data_dir)
        if not batch_list:
            console.print("[yellow]⚠️  没有扫描批次记录[/yellow]")
            return
        table = Table(show_header=True, header_style="bold blue", title=f"扫描批次 ({len(batch_list)} 个)")
        table.add_column("批次ID")
        table.add_column("扫描时间")
        table.add_column("文件夹")
        table.add_column("总数", justify="right")
        table.add_column("新增", justify="right", style="green")
        table.add_column("更新", justify="right", style="yellow")
        table.add_column("未变化", justify="right")
        table.add_column("规则")
        for b in batch_list:
            table.add_row(
                b.batch_id, b.scan_time, b.folder,
                str(b.total_count), str(b.new_count),
                str(b.updated_count), str(b.unchanged_count),
                b.rule_name,
            )
        console.print(table)
        return

    contracts = load_contracts(data_dir)
    if not contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    if batch_id:
        batch_contracts = get_contracts_by_batch(batch_id, data_dir)
        if not batch_contracts:
            console.print(f"[yellow]⚠️  批次 {batch_id} 不存在或没有合同[/yellow]")
            return
        console.print(f"   使用批次快照: {batch_id} ({len(batch_contracts)} 份合同)")
        contracts = batch_contracts

    rule = load_rule(data_dir)
    contracts = check_all_contracts(contracts, rule)

    issue_type_val = IssueType(issue_type) if issue_type else None
    follow_priority_val = PriorityLevel(follow_priority) if follow_priority else None

    start_d = date.fromisoformat(start_date) if start_date else None
    end_d = date.fromisoformat(end_date) if end_date else None

    contracts = filter_contracts(
        contracts,
        room=room,
        expire_month=expire_month,
        agent=agent,
        issue_type=issue_type_val,
        high_risk_only=high_risk_only,
        batch_id=batch_id,
        start_date=start_d,
        end_date=end_d,
        follow_operator=follow_operator,
        follow_overdue_only=follow_overdue,
        follow_due_today_only=follow_due_today,
        follow_priority=follow_priority_val,
        change_risk_only=change_risk,
    )

    if not contracts:
        console.print("[yellow]⚠️  没有符合条件的合同[/yellow]")
        return

    if follow_summary:
        from collections import defaultdict
        summary = defaultdict(list)
        for c in contracts:
            all_fu = c.pending_follow_ups
            for fu in all_fu:
                op = fu.operator or "未指定负责人"
                summary[op].append((c, fu))

        title_parts = ["跟进任务汇总"]
        if follow_overdue:
            title_parts.append("【逾期】")
        if follow_due_today:
            title_parts.append("【今日到期】")
        if follow_operator:
            title_parts.append(f"【负责人:{follow_operator}】")

        table = Table(show_header=True, header_style="bold blue",
                      title=f"{''.join(title_parts)} (共 {sum(len(v) for v in summary.values())} 项任务)")
        table.add_column("负责人", style="bold")
        table.add_column("任务数", justify="right")
        table.add_column("紧急", justify="right", style="bold red")
        table.add_column("高优", justify="right", style="red")
        table.add_column("中优", justify="right", style="yellow")
        table.add_column("低优", justify="right", style="green")
        table.add_column("逾期", justify="right", style="bold red")
        table.add_column("今日到期", justify="right", style="bold yellow")

        for op in sorted(summary.keys()):
            items = summary[op]
            urgent = sum(1 for _, fu in items if fu.priority == PriorityLevel.URGENT)
            high = sum(1 for _, fu in items if fu.priority == PriorityLevel.HIGH)
            medium = sum(1 for _, fu in items if fu.priority == PriorityLevel.MEDIUM)
            low = sum(1 for _, fu in items if fu.priority == PriorityLevel.LOW)
            overdue = sum(1 for _, fu in items if fu.is_overdue)
            due_today = sum(1 for _, fu in items if fu.is_due_today)

            table.add_row(
                op,
                str(len(items)),
                str(urgent) if urgent > 0 else "-",
                str(high) if high > 0 else "-",
                str(medium) if medium > 0 else "-",
                str(low) if low > 0 else "-",
                str(overdue) if overdue > 0 else "-",
                str(due_today) if due_today > 0 else "-",
            )
        console.print(table)

        for op in sorted(summary.keys()):
            items = sorted(summary[op], key=lambda x: (
                0 if x[1].is_overdue else 1,
                0 if x[1].is_due_today else 1,
                {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(x[1].priority.value, 4),
            ))
            console.print(f"\n[bold]📋 {op} - 待处理跟进任务 ({len(items)} 项)[/bold]")
            detail_table = Table(show_header=True, header_style="bold", show_lines=False)
            detail_table.add_column("优先级", width=8)
            detail_table.add_column("状态", width=10)
            detail_table.add_column("预计完成")
            detail_table.add_column("房号")
            detail_table.add_column("动作")
            detail_table.add_column("内容")
            detail_table.add_column("下次跟进")

            for c, fu in items:
                pri_color = {"urgent": "bold red", "high": "red", "medium": "yellow", "low": "green"}.get(fu.priority.value, "dim")
                status = ""
                if fu.is_overdue:
                    status = Text("⚠️ 逾期", style="bold red")
                elif fu.is_due_today:
                    status = Text("📅 今日", style="bold yellow")

                detail_table.add_row(
                    Text(priority_label(fu.priority), style=pri_color),
                    status,
                    fu.expected_date[:10] if fu.expected_date else "-",
                    c.room_number or "-",
                    follow_up_action_label(fu.action),
                    fu.content,
                    fu.next_follow_date[:10] if fu.next_follow_date else "-",
                )
            console.print(detail_table)

        return

    contracts = sort_contracts(contracts, sort_by)

    table = Table(show_header=True, header_style="bold blue", title=f"合同列表 ({len(contracts)} 份)")
    table.add_column("文件", style="dim")
    table.add_column("房号")
    table.add_column("租客")
    table.add_column("租期结束")
    table.add_column("租金", justify="right")
    table.add_column("经纪人")
    table.add_column("风险", justify="center")
    table.add_column("待处理", justify="right")
    table.add_column("已处理", justify="right")
    table.add_column("最近跟进")
    table.add_column("变更", justify="right")

    for c in contracts:
        color = risk_color(c.risk_level)
        latest = c.latest_follow_up
        if latest:
            follow_info = f"{follow_up_action_label(latest.action)}"
            if latest.operator:
                follow_info += f"@{latest.operator}"
        else:
            follow_info = "-"
        table.add_row(
            Path(c.file_path).name,
            c.room_number or "-",
            c.tenant_name or "-",
            str(c.end_date) if c.end_date else "-",
            f"{c.monthly_rent:.0f}" if c.monthly_rent else "-",
            c.agent_name or "-",
            Text(risk_level_label(c.risk_level), style=f"bold {color}"),
            str(c.pending_issues_count),
            str(c.resolved_issues_count),
            follow_info,
            str(len(c.field_changes)),
        )

    console.print(table)


@cli.command("export", help="导出报表到文件")
@click.argument("report_type", type=click.Choice(["pending", "expiring", "summary", "progress", "all", "by-agent"]))
@click.option("--output", "-o", type=click.Path(), help="输出文件路径(单报表)或目录(all/by-agent)")
@click.option("--days", type=int, default=None, help="到期清单: 未来N天内到期 (默认使用规则配置)")
@click.option("--high-risk-only", is_flag=True, help="只包含高风险合同")
@click.option("--room", help="按房源筛选")
@click.option("--agent", help="按经纪人筛选")
@click.option("--batch-id", help="按扫描批次筛选")
@click.option("--start-date", help="租期开始日期(YYYY-MM-DD)起")
@click.option("--end-date", help="租期结束日期(YYYY-MM-DD)止")
@click.option("--format", "fmt", type=click.Choice(["xlsx", "csv"]), default="xlsx", help="导出格式")
@click.option("--split-by-agent", is_flag=True, help="export all时按经纪人拆分额外输出")
@click.option("--detail", is_flag=True, help="export progress时额外导出明细行(按问题展开)")
@click.pass_context
def export_cmd(ctx, report_type, output, days, high_risk_only, room, agent,
               batch_id, start_date, end_date, fmt, split_by_agent, detail):
    data_dir = ctx.obj["data_dir"]
    contracts = load_contracts(data_dir)

    if not contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    if batch_id:
        batch_contracts = get_contracts_by_batch(batch_id, data_dir)
        if not batch_contracts:
            console.print(f"[yellow]⚠️  批次 {batch_id} 不存在或没有合同[/yellow]")
            return
        console.print(f"   使用批次快照: {batch_id} ({len(batch_contracts)} 份合同)")
        contracts = batch_contracts

    rule = load_rule(data_dir)
    contracts = check_all_contracts(contracts, rule)

    if days is None:
        days = rule.expiring_days_default
    else:
        console.print(f"   使用自定义到期天数: {days} 天 (规则默认: {rule.expiring_days_default} 天)")

    start_d = date.fromisoformat(start_date) if start_date else None
    end_d = date.fromisoformat(end_date) if end_date else None

    contracts = filter_contracts(
        contracts,
        room=room,
        agent=agent,
        high_risk_only=high_risk_only,
        start_date=start_d,
        end_date=end_d,
    )

    if not contracts and report_type != "all":
        console.print("[yellow]⚠️  没有符合条件的合同可导出[/yellow]")
        return

    ext = f".{fmt}"

    if report_type == "all":
        out_dir = output or "contract_reports"
        paths = export_all(contracts, out_dir, days=days, split_by_agent=split_by_agent, fmt=fmt)
        console.print("[bold green]✅ 所有报表已导出:[/bold green]")
        for p in paths:
            console.print(f"   📄 {p}")
        console.print(f"   共 {len(contracts)} 份合同数据")
        if split_by_agent:
            agents = sorted(set(c.agent_name or "未指定经纪人" for c in contracts))
            console.print(f"   按 {len(agents)} 位经纪人拆分输出")
        return

    if report_type == "by-agent":
        out_dir = output or "reports_by_agent"
        paths = export_by_agent(contracts, out_dir, days=days, fmt=fmt)
        agents = sorted(set(c.agent_name or "未指定经纪人" for c in contracts))
        console.print(f"[bold green]✅ 已按经纪人拆分导出:[/bold green]")
        console.print(f"   共 {len(agents)} 位经纪人，{len(paths)} 个文件")
        for agent in agents:
            count = sum(1 for c in contracts if (c.agent_name or "未指定经纪人") == agent)
            console.print(f"   👤 {agent}: {count} 份合同 → {out_dir}/{agent.replace('/', '_').replace(chr(92), '_').replace(' ', '')}/")
        return

    if report_type == "pending":
        if not output:
            output = f"待补充清单{ext}"
        export_pending_list(contracts, output)
        items = get_pending_items(contracts)
        console.print(f"[bold green]✅ 待补充清单已导出到: {output}[/bold green]")
        console.print(f"   共 {len(items)} 条待处理项")

    elif report_type == "expiring":
        if not output:
            output = f"到期清单_{days}天{ext}"
        export_expiring_list(contracts, output, days)
        items = get_expiring_contracts(contracts, days)
        console.print(f"[bold green]✅ 到期清单已导出到: {output}[/bold green]")
        console.print(f"   未来 {days} 天内到期共 {len(items)} 份合同")

    elif report_type == "summary":
        if not output:
            output = f"合同摘要{ext}"
        export_contract_summary(contracts, output)
        console.print(f"[bold green]✅ 合同摘要已导出到: {output}[/bold green]")
        console.print(f"   共 {len(contracts)} 份合同")

    elif report_type == "progress":
        if not output:
            output = f"处理进度表{ext}"
        export_review_progress(contracts, output)
        console.print(f"[bold green]✅ 处理进度表已导出到: {output}[/bold green]")
        console.print(f"   共 {len(contracts)} 份合同")
        if detail:
            from pathlib import Path
            detail_path = str(Path(output).with_name(f"跟进明细表{ext}"))
            export_review_progress_detail(contracts, detail_path)
            console.print(f"[bold green]✅ 跟进明细表已导出到: {detail_path}[/bold green]")
            from exporter import get_review_progress_detail
            items = get_review_progress_detail(contracts)
            console.print(f"   共 {len(items)} 条问题明细")


@cli.command("review", help="逐份审核合同，标记问题状态")
@click.option("--high-risk-only", is_flag=True, help="只审核高风险合同")
@click.option("--sort-by", type=click.Choice(["risk", "end_date", "room"]), default="risk", help="排序方式")
@click.option("--room", help="按房源筛选")
@click.option("--agent", help="按经纪人筛选")
@click.option("--export-progress", type=click.Path(), help="审核完成后导出处理进度表")
@click.pass_context
def review(ctx, high_risk_only, sort_by, room, agent, export_progress):
    data_dir = ctx.obj["data_dir"]
    contracts = load_contracts(data_dir)

    if not contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    rule = load_rule(data_dir)
    contracts = check_all_contracts(contracts, rule)

    contracts = filter_contracts(
        contracts,
        room=room,
        agent=agent,
        high_risk_only=high_risk_only,
    )

    contracts = sort_contracts(contracts, sort_by)
    contracts = [c for c in contracts if c.issues]

    if not contracts:
        console.print("[bold green]🎉 没有需要审核的合同![/bold green]")
        return

    console.print(f"📋 开始审核，共 {len(contracts)} 份合同待处理")
    console.print("   操作说明: 输入问题编号，然后选择状态 (1=待处理, 2=已确认, 3=已补充, 4=已忽略)")
    console.print("   其他命令: n=下一份, p=上一份, q=退出, s=保存, a=全部跳过\n")

    idx = 0
    modified = False

    while 0 <= idx < len(contracts):
        contract = contracts[idx]
        console.clear() if False else None
        console.print(f"[bold]--- 第 {idx+1}/{len(contracts)} 份 ---[/bold]")
        display_contract_card(contract, show_issues=True, show_status=True)

        if not contract.issues:
            console.print("[dim]无问题，自动跳过[/dim]")
            idx += 1
            continue

        choice = Prompt.ask(
            "\n操作",
            choices=[str(i) for i in range(1, len(contract.issues)+1)] + ["n", "p", "q", "s", "a"],
            default="n",
        )

        if choice == "q":
            console.print("\n[yellow]⏹  退出审核[/yellow]")
            break
        elif choice == "n":
            idx += 1
        elif choice == "p":
            idx = max(0, idx - 1)
        elif choice == "s":
            update_contracts(contracts, data_dir)
            modified = False
            console.print("[green]✅ 已保存[/green]")
            continue
        elif choice == "a":
            if Confirm.ask("确定要跳过所有剩余合同吗?"):
                break
        else:
            issue_idx = int(choice) - 1
            if 0 <= issue_idx < len(contract.issues):
                issue = contract.issues[issue_idx]
                console.print(f"\n当前问题: [{issue_type_label(issue.issue_type)}] {issue.description}")
                console.print(f"当前状态: {issue_status_label(issue.status)}")

                status_choice = Prompt.ask(
                    "设置状态",
                    choices=["1", "2", "3", "4", "c"],
                    default="c",
                    show_choices=False,
                )
                console.print("  1=待处理  2=已确认  3=已补充  4=已忽略  c=取消")

                if status_choice == "c":
                    continue

                status_map = {
                    "1": IssueStatus.PENDING,
                    "2": IssueStatus.CONFIRMED,
                    "3": IssueStatus.RESOLVED,
                    "4": IssueStatus.IGNORED,
                }
                new_status = status_map.get(status_choice)
                if new_status:
                    note = Prompt.ask("备注(可选)", default="")
                    issue.mark_status(new_status, note)
                    modified = True
                    console.print(f"[green]✅ 已标记为 {issue_status_label(new_status)}[/green]")

    if modified:
        if Confirm.ask("有未保存的更改，是否保存?"):
            update_contracts(contracts, data_dir)
            console.print("[green]✅ 已保存[/green]")

    pending_total = sum(c.pending_issues_count for c in contracts)
    resolved_total = sum(c.resolved_issues_count for c in contracts)
    console.print(f"\n📊 审核统计: 待处理 {pending_total} | 已处理 {resolved_total}")

    if export_progress:
        export_review_progress(load_contracts(data_dir), export_progress)
        console.print(f"📄 处理进度表已导出: {export_progress}")


@cli.command("follow-up", help="记录合同跟进动作（补签、补证件、改租金等）")
@click.option("--room", help="按房号筛选合同")
@click.option("--agent", help="按经纪人筛选")
@click.option("--high-risk-only", is_flag=True, help="只跟进高风险合同")
@click.option("--all", "follow_all", is_flag=True, help="非交互批量模式：给所有合同登记一条跟进")
@click.option("--action", type=click.Choice([
    "sign_supplement", "id_supplement", "rent_adjust", "deposit_adjust",
    "date_correct", "phone_call", "wechat", "visit", "other"
]), help="跟进动作类型")
@click.option("--content", help="跟进内容描述")
@click.option("--operator", help="跟进负责人")
@click.option("--issue-idx", type=int, default=-1, help="指定问题编号(从1开始)，不指定则记录到合同级别")
@click.option("--priority", type=click.Choice(["low", "medium", "high", "urgent"]),
              default="medium", help="优先级 (low/medium/high/urgent)")
@click.option("--expected-date", help="预计完成日期 YYYY-MM-DD")
@click.option("--next-follow-date", help="下次跟进日期 YYYY-MM-DD")
@click.option("--complete", is_flag=True, help="标记该跟进已完成")
@click.option("--export", "export_path", type=click.Path(), help="完成后导出处理进度表")
@click.pass_context
def follow_up_cmd(ctx, room, agent, high_risk_only, follow_all, action,
                  content, operator, issue_idx, priority, expected_date,
                  next_follow_date, complete, export_path):
    data_dir = ctx.obj["data_dir"]
    all_contracts = load_contracts(data_dir)

    if not all_contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    rule = load_rule(data_dir)
    all_contracts = check_all_contracts(all_contracts, rule)

    filtered = filter_contracts(
        all_contracts,
        room=room,
        agent=agent,
        high_risk_only=high_risk_only,
    )

    if not filtered:
        console.print("[yellow]⚠️  没有符合条件的合同[/yellow]")
        return

    if follow_all:
        if not action or not content:
            console.print("[red]❌ 批量模式必须指定 --action 和 --content[/red]")
            return
        action_val = FollowUpAction(action)
        priority_val = PriorityLevel(priority)
        count = 0
        for c in filtered:
            issue_index = issue_idx - 1 if issue_idx > 0 else -1
            c.add_follow_up(action_val, content, operator=operator, issue_index=issue_index,
                            expected_date=expected_date, next_follow_date=next_follow_date,
                            priority=priority_val, completed=complete)
            count += 1
        update_contracts(filtered, data_dir)
        console.print(f"[bold green]✅ 批量跟进完成[/bold green]")
        console.print(f"   共登记 {count} 条跟进: {follow_up_action_label(action_val)} - {content}")
        if operator:
            console.print(f"   负责人: {operator}")
        if priority != "medium":
            console.print(f"   优先级: {priority_label(priority_val)}")
        if expected_date:
            console.print(f"   预计完成: {expected_date}")
        if next_follow_date:
            console.print(f"   下次跟进: {next_follow_date}")
        if complete:
            console.print(f"   [green]已标记完成[/green]")

    else:
        console.print(f"📋 共 {len(filtered)} 份合同可选，开始交互跟进\n")
        idx = 0
        modified = False

        while 0 <= idx < len(filtered):
            c = filtered[idx]
            console.print(f"[bold]--- 第 {idx+1}/{len(filtered)} 份 ---[/bold]")
            display_contract_card(c, show_issues=True, show_status=True)

            choice = Prompt.ask(
                "\n操作",
                choices=["a", "f", "n", "p", "q", "s"],
                default="n",
            )
            console.print("  a=登记跟进  f=查看跟进历史  n=下一份  p=上一份  q=退出  s=保存")

            if choice == "q":
                console.print("\n[yellow]⏹  退出跟进[/yellow]")
                break
            elif choice == "n":
                idx += 1
            elif choice == "p":
                idx = max(0, idx - 1)
            elif choice == "s":
                update_contracts(filtered, data_dir)
                modified = False
                console.print("[green]✅ 已保存[/green]")
                continue
            elif choice == "f":
                console.print("\n📞 跟进历史:")
                all_fu: list = []
                for fu in c.follow_ups:
                    all_fu.append((-1, fu))
                for i, issue in enumerate(c.issues):
                    for fu in issue.follow_ups:
                        all_fu.append((i, fu))
                all_fu.sort(key=lambda x: x[1].follow_time)
                if not all_fu:
                    console.print("   (暂无跟进记录)")
                for i, fu in all_fu:
                    scope = f"问题[{i+1}]" if i >= 0 else "合同"
                    ct = fu.follow_time[:16].replace("T", " ")
                    op = f" ({fu.operator})" if fu.operator else ""
                    pri = f" [{priority_label(fu.priority)}]" if fu.priority != PriorityLevel.MEDIUM else ""
                    exp = f" ⏰{fu.expected_date[:10]}" if fu.expected_date else ""
                    done = " ✅" if fu.completed else ""
                    overdue = " ⚠️逾期" if fu.is_overdue else ""
                    due_today = " 📅今日到期" if fu.is_due_today else ""
                    console.print(f"   [{ct}] {scope} {follow_up_action_label(fu.action)}: {fu.content}{op}{pri}{exp}{done}{overdue}{due_today}")
                console.print("")
                continue
            elif choice == "a":
                if not action:
                    act_choice = Prompt.ask(
                        "选择跟进动作",
                        choices=["1", "2", "3", "4", "5", "6", "7", "8", "9"],
                        default="6",
                    )
                    console.print("  1=补签 2=补证件 3=改租金 4=改押金 5=改日期 6=电话 7=微信 8=上门 9=其他")
                    action_map = {
                        "1": FollowUpAction.SIGN_SUPPLEMENT,
                        "2": FollowUpAction.ID_SUPPLEMENT,
                        "3": FollowUpAction.RENT_ADJUST,
                        "4": FollowUpAction.DEPOSIT_ADJUST,
                        "5": FollowUpAction.DATE_CORRECT,
                        "6": FollowUpAction.PHONE_CALL,
                        "7": FollowUpAction.WECHAT,
                        "8": FollowUpAction.VISIT,
                        "9": FollowUpAction.OTHER,
                    }
                    action_val = action_map[act_choice]
                else:
                    action_val = FollowUpAction(action)

                if issue_idx <= 0 and c.issues:
                    issue_sel = Prompt.ask(
                        "关联哪个问题? (0=合同级别, 留空=选问题编号)",
                        default="0",
                    )
                    try:
                        sel = int(issue_sel)
                        issue_index = sel - 1 if sel > 0 else -1
                    except ValueError:
                        issue_index = -1
                else:
                    issue_index = issue_idx - 1 if issue_idx > 0 else -1

                if not content:
                    fu_content = Prompt.ask("跟进内容")
                else:
                    fu_content = content

                if not operator:
                    fu_operator = Prompt.ask("负责人(可留空)", default="")
                else:
                    fu_operator = operator

                if priority == "medium":
                    p_choice = Prompt.ask(
                        "优先级? (1=低 2=中 3=高 4=紧急)",
                        choices=["1", "2", "3", "4"],
                        default="2",
                    )
                    p_map = {"1": PriorityLevel.LOW, "2": PriorityLevel.MEDIUM,
                             "3": PriorityLevel.HIGH, "4": PriorityLevel.URGENT}
                    fu_priority = p_map[p_choice]
                else:
                    fu_priority = PriorityLevel(priority)

                if not expected_date:
                    fu_expected = Prompt.ask("预计完成日期 YYYY-MM-DD (可留空)", default="")
                else:
                    fu_expected = expected_date

                if not next_follow_date:
                    fu_next = Prompt.ask("下次跟进日期 YYYY-MM-DD (可留空)", default="")
                else:
                    fu_next = next_follow_date

                fu_completed = complete or Confirm.ask("标记为已完成?", default=False)

                c.add_follow_up(action_val, fu_content, operator=fu_operator, issue_index=issue_index,
                                expected_date=fu_expected or None, next_follow_date=fu_next or None,
                                priority=fu_priority, completed=fu_completed)
                modified = True
                status = "[green]✓已完成[/green]" if fu_completed else ""
                console.print(f"[green]✅ 已登记跟进: {follow_up_action_label(action_val)} - {fu_content}[/green] {status}")

        if modified:
            if Confirm.ask("有未保存的更改，是否保存?"):
                update_contracts(filtered, data_dir)
                console.print("[green]✅ 已保存[/green]")

    if export_path:
        export_review_progress(load_contracts(data_dir), export_path)
        console.print(f"📄 处理进度表已导出: {export_path}")


@cli.group("rule", help="规则配置管理")
def rule_cmd():
    pass


@rule_cmd.command("show", help="显示当前规则配置")
@click.pass_context
def rule_show(ctx):
    data_dir = ctx.obj["data_dir"]
    rule = load_rule(data_dir)

    table = Table(show_header=True, header_style="bold blue", title=f"规则配置: {rule.get_display_name()}")
    table.add_column("配置项")
    table.add_column("值")

    table.add_row("规则名称", rule.rule_name)
    table.add_row("租金异常阈值", f"±{rule.rent_deviation_threshold*100:.0f}%")
    table.add_row("押金倍数", ", ".join(str(r) for r in rule.deposit_multiples))
    table.add_row("押金容差", f"±{rule.deposit_tolerance*100:.0f}%")
    table.add_row("默认到期天数", f"{rule.expiring_days_default} 天")
    table.add_row("最低租金阈值", f"{rule.min_rent_amount:.0f} 元")
    table.add_row("经纪人签名检查", "是" if rule.require_agent_signature else "否")
    table.add_row("高风险问题类型", ", ".join(issue_type_label(t) for t in rule.high_risk_issue_types))

    console.print(table)


@rule_cmd.command("init", help="生成示例规则配置文件")
@click.option("--output", "-o", default="rule_config.json", help="输出文件路径")
@click.option("--force", is_flag=True, help="覆盖已存在的文件")
@click.pass_context
def rule_init(ctx, output, force):
    data_dir = ctx.obj["data_dir"]
    if os.path.exists(output) and not force:
        console.print(f"[yellow]⚠️  文件 {output} 已存在，使用 --force 覆盖[/yellow]")
        return

    rule = RuleConfig(rule_name="default")
    save_rule(rule, data_dir)
    import json
    with open(output, "w", encoding="utf-8") as f:
        f.write(rule.model_dump_json(indent=2, ensure_ascii=False))
    console.print(f"[green]✅ 示例规则配置已生成: {output}[/green]")
    console.print("   可修改后通过 rule apply 应用")


@rule_cmd.command("apply", help="应用规则配置文件")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def rule_apply(ctx, file):
    data_dir = ctx.obj["data_dir"]
    import json
    with open(file, "r", encoding="utf-8") as f:
        rule_data = json.load(f)
    rule = RuleConfig.model_validate(rule_data)
    save_rule(rule, data_dir)
    console.print(f"[green]✅ 已应用规则: {rule.get_display_name()}[/green]")

    contracts = load_contracts(data_dir)
    if contracts:
        contracts = check_all_contracts(contracts, rule)
        save_contracts(contracts, data_dir)
        high = sum(1 for c in contracts if c.risk_level == RiskLevel.HIGH)
        console.print(f"   已使用新规则重新检查 {len(contracts)} 份合同")
        console.print(f"   高风险: {high} 份")


if __name__ == "__main__":
    cli()
