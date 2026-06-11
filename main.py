from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from checker import check_all_contracts
from exporter import (
    export_all,
    export_contract_summary,
    export_expiring_list,
    export_pending_list,
    get_contract_summary,
    get_expiring_contracts,
    get_pending_items,
    payment_method_label,
    risk_level_label,
)
from models import Contract, IssueType, RiskLevel
from scanner import scan_folder
from storage import get_scan_time, load_contracts, save_contracts


console = Console()


def risk_color(level: RiskLevel) -> str:
    return {RiskLevel.LOW: "green", RiskLevel.MEDIUM: "yellow", RiskLevel.HIGH: "red"}.get(
        level, "white"
    )


def issue_type_label(it: IssueType) -> str:
    labels = {
        "missing_signature": "缺少签名",
        "date_conflict": "日期冲突",
        "lease_overlap": "租期重叠",
        "abnormal_rent": "租金异常",
        "deposit_mismatch": "押金不一致",
        "invalid_id_number": "身份证号问题",
    }
    return labels.get(getattr(it, "value", it), str(it))


def sort_contracts(contracts, sort_by: str):
    if sort_by == "risk":
        risk_order = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}
        return sorted(contracts, key=lambda c: (risk_order.get(c.risk_level, 3), c.room_number))
    elif sort_by == "end_date":
        return sorted(contracts, key=lambda c: (c.end_date or date.max, c.room_number))
    elif sort_by == "room":
        return sorted(contracts, key=lambda c: (c.room_number, c.end_date or date.max))
    elif sort_by == "rent":
        return sorted(contracts, key=lambda c: (-c.monthly_rent, c.room_number))
    return contracts


def display_contract_card(c: Contract, show_issues: bool = True) -> None:
    from rich.console import Group
    from rich.text import Text

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

    if show_issues and c.issues:
        elements.append(Text(""))
        elements.append(Text("⚠️  问题列表:", style="bold red"))
        for issue in c.issues:
            ic = risk_color(issue.risk_level)
            issue_line = Text("   ")
            issue_line.append("● ", style=ic)
            issue_line.append(f"[{issue_type_label(issue.issue_type)}] {issue.description}")
            elements.append(issue_line)
            if issue.suggestion:
                sug_line = Text(f"      💡 建议: {issue.suggestion}", style="dim")
                elements.append(sug_line)

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
@click.option("--auto-check/--no-auto-check", default=True, help="扫描后自动执行检查")
@click.option("--verbose/--no-verbose", default=False, help="显示详细识别结果")
@click.pass_context
def scan(ctx, folder, auto_check, verbose):
    data_dir = ctx.obj["data_dir"]
    console.print(f"[bold blue]🔍 正在扫描文件夹:[/bold blue] {folder}")

    try:
        contracts = scan_folder(folder)
    except Exception as e:
        console.print(f"[bold red]❌ 扫描失败: {e}[/bold red]")
        return

    if not contracts:
        console.print("[yellow]⚠️  未找到任何合同文件(.txt/.md)[/yellow]")
        return

    console.print(f"[bold green]✅ 成功扫描 {len(contracts)} 份合同[/bold green]")

    if auto_check:
        contracts = check_all_contracts(contracts)
        high_risk = sum(1 for c in contracts if c.risk_level == RiskLevel.HIGH)
        medium_risk = sum(1 for c in contracts if c.risk_level == RiskLevel.MEDIUM)
        console.print(f"[bold]检查结果:[/bold] 高风险 {high_risk} 份, 中风险 {medium_risk} 份, 正常 {len(contracts) - high_risk - medium_risk} 份")

    save_contracts(contracts, data_dir)
    console.print(f"[dim]💾 数据已保存[/dim]")

    if verbose:
        for c in contracts:
            display_contract_card(c, show_issues=auto_check)


@cli.command(help="按规则检查合同问题")
@click.option("--high-risk-only", is_flag=True, help="只显示高风险合同")
@click.option("--sort-by", type=click.Choice(["risk", "end_date", "room", "rent"]), default="risk", help="排序方式")
@click.pass_context
def check(ctx, high_risk_only, sort_by):
    data_dir = ctx.obj["data_dir"]
    contracts = load_contracts(data_dir)

    if not contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    scan_time = get_scan_time(data_dir)
    if scan_time:
        console.print(f"[dim]📅 扫描时间: {scan_time}[/dim]")

    contracts = check_all_contracts(contracts)
    save_contracts(contracts, data_dir)

    if high_risk_only:
        contracts = [c for c in contracts if c.risk_level == RiskLevel.HIGH]
        if not contracts:
            console.print("[bold green]🎉 没有高风险合同![/bold green]")
            return

    contracts = sort_contracts(contracts, sort_by)

    high = sum(1 for c in contracts if c.risk_level == RiskLevel.HIGH)
    medium = sum(1 for c in contracts if c.risk_level == RiskLevel.MEDIUM)
    low = sum(1 for c in contracts if c.risk_level == RiskLevel.LOW and not c.issues)
    console.print(f"\n[bold]共 {len(contracts)} 份合同: [/bold][red]高风险 {high}[/red], [yellow]中风险 {medium}[/yellow], [green]正常 {low}[/green]\n")

    for c in contracts:
        display_contract_card(c)


@cli.command(help="列出合同，支持多种筛选条件")
@click.option("--room", help="按房源/房号筛选(支持模糊匹配)")
@click.option("--expire-month", help="按到期月份筛选，格式 YYYY-MM (如 2025-06)")
@click.option("--agent", help="按经纪人筛选")
@click.option("--issue-type", type=click.Choice([
    "missing_signature", "date_conflict", "lease_overlap",
    "abnormal_rent", "deposit_mismatch", "invalid_id_number"
]), help="按异常类型筛选")
@click.option("--high-risk-only", is_flag=True, help="只显示高风险合同")
@click.option("--sort-by", type=click.Choice(["risk", "end_date", "room", "rent"]), default="end_date", help="排序方式")
@click.pass_context
def list(ctx, room, expire_month, agent, issue_type, high_risk_only, sort_by):
    data_dir = ctx.obj["data_dir"]
    contracts = load_contracts(data_dir)

    if not contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    contracts = check_all_contracts(contracts)

    if room:
        contracts = [c for c in contracts if room.lower() in (c.room_number or "").lower()]
    if expire_month:
        try:
            year, month = map(int, expire_month.split("-"))
            contracts = [c for c in contracts if c.end_date and c.end_date.year == year and c.end_date.month == month]
        except ValueError:
            console.print("[bold red]❌ 到期月份格式错误，应为 YYYY-MM (如 2025-06)[/bold red]")
            return
    if agent:
        contracts = [c for c in contracts if agent.lower() in (c.agent_name or "").lower()]
    if issue_type:
        it = IssueType(issue_type)
        contracts = [c for c in contracts if any(i.issue_type == it for i in c.issues)]
    if high_risk_only:
        contracts = [c for c in contracts if c.risk_level == RiskLevel.HIGH]

    if not contracts:
        console.print("[yellow]⚠️  没有符合条件的合同[/yellow]")
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
    table.add_column("问题数", justify="right")

    for c in contracts:
        color = risk_color(c.risk_level)
        table.add_row(
            Path(c.file_path).name,
            c.room_number or "-",
            c.tenant_name or "-",
            str(c.end_date) if c.end_date else "-",
            f"{c.monthly_rent:.0f}" if c.monthly_rent else "-",
            c.agent_name or "-",
            Text(risk_level_label(c.risk_level), style=f"bold {color}"),
            str(len(c.issues)),
        )

    console.print(table)


@cli.command(help="导出报表到文件")
@click.argument("report_type", type=click.Choice(["pending", "expiring", "summary", "all"]))
@click.option("--output", "-o", type=click.Path(), help="输出文件路径(单报表)或目录(all)")
@click.option("--days", type=int, default=30, help="到期清单: 未来N天内到期 (默认30)")
@click.option("--high-risk-only", is_flag=True, help="待补充清单: 只包含高风险")
@click.pass_context
def export(ctx, report_type, output, days, high_risk_only):
    data_dir = ctx.obj["data_dir"]
    contracts = load_contracts(data_dir)

    if not contracts:
        console.print("[yellow]⚠️  没有合同数据，请先运行 scan 命令[/yellow]")
        return

    contracts = check_all_contracts(contracts)

    if report_type == "all":
        out_dir = output or "contract_reports"
        paths = export_all(contracts, out_dir, days)
        console.print("[bold green]✅ 所有报表已导出:[/bold green]")
        for p in paths:
            console.print(f"   📄 {p}")
        return

    if report_type == "pending":
        items = get_pending_items(contracts)
        if high_risk_only:
            items = [i for i in items if i["高风险问题数"] > 0]
        if not output:
            output = "待补充清单.xlsx"
        if output.endswith(".xlsx"):
            from exporter import write_excel
            write_excel(items, output, "待补充清单")
        else:
            export_pending_list(contracts, output)
        console.print(f"[bold green]✅ 待补充清单已导出到: {output}[/bold green]")
        console.print(f"   共 {len(items)} 条待处理项")

    elif report_type == "expiring":
        if not output:
            output = f"到期清单_{days}天.xlsx"
        export_expiring_list(contracts, output, days)
        items = get_expiring_contracts(contracts, days)
        console.print(f"[bold green]✅ 到期清单已导出到: {output}[/bold green]")
        console.print(f"   未来 {days} 天内到期共 {len(items)} 份合同")

    elif report_type == "summary":
        if not output:
            output = "合同摘要.xlsx"
        export_contract_summary(contracts, output)
        console.print(f"[bold green]✅ 合同摘要已导出到: {output}[/bold green]")
        console.print(f"   共 {len(contracts)} 份合同")


if __name__ == "__main__":
    cli()
