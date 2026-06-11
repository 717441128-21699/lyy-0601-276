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
    export_contract_summary,
    export_expiring_list,
    export_pending_list,
    export_review_progress,
    filter_contracts,
    get_contract_summary,
    get_expiring_contracts,
    get_pending_items,
    issue_status_label,
    issue_type_label,
    payment_method_label,
    risk_level_label,
    sort_contracts,
)
from models import Contract, IssueType, RiskLevel, IssueStatus, RuleConfig
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
@click.pass_context
def check_cmd(ctx, high_risk_only, sort_by, rule_file, show_rule):
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

    contracts = sort_contracts(contracts, sort_by)

    high = sum(1 for c in contracts if c.risk_level == RiskLevel.HIGH)
    medium = sum(1 for c in contracts if c.risk_level == RiskLevel.MEDIUM)
    low = sum(1 for c in contracts if c.risk_level == RiskLevel.LOW)
    console.print(f"\n[bold]共 {len(contracts)} 份合同: [/bold]"
                  f"[red]高风险 {high}[/red], "
                  f"[yellow]中风险 {medium}[/yellow], "
                  f"[green]低/无 {low}[/green]\n")

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
@click.pass_context
def list_cmd(ctx, room, expire_month, agent, issue_type, high_risk_only,
             batch_id, start_date, end_date, sort_by, batches):
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

    start_d = date.fromisoformat(start_date) if start_date else None
    end_d = date.fromisoformat(end_date) if end_date else None

    contracts = filter_contracts(
        contracts,
        room=room,
        expire_month=expire_month,
        agent=agent,
        issue_type=issue_type_val,
        high_risk_only=high_risk_only,
        start_date=start_d,
        end_date=end_d,
    )

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
    table.add_column("待处理", justify="right")
    table.add_column("已处理", justify="right")

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
            str(c.pending_issues_count),
            str(c.resolved_issues_count),
        )

    console.print(table)


@cli.command("export", help="导出报表到文件")
@click.argument("report_type", type=click.Choice(["pending", "expiring", "summary", "progress", "all"]))
@click.option("--output", "-o", type=click.Path(), help="输出文件路径(单报表)或目录(all)")
@click.option("--days", type=int, default=None, help="到期清单: 未来N天内到期 (默认使用规则配置)")
@click.option("--high-risk-only", is_flag=True, help="只包含高风险合同")
@click.option("--room", help="按房源筛选")
@click.option("--agent", help="按经纪人筛选")
@click.option("--batch-id", help="按扫描批次筛选")
@click.option("--start-date", help="租期开始日期(YYYY-MM-DD)起")
@click.option("--end-date", help="租期结束日期(YYYY-MM-DD)止")
@click.option("--format", "fmt", type=click.Choice(["xlsx", "csv"]), default="xlsx", help="导出格式")
@click.pass_context
def export_cmd(ctx, report_type, output, days, high_risk_only, room, agent,
               batch_id, start_date, end_date, fmt):
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
        paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        pending_path = str(Path(out_dir) / f"待补充清单_{timestamp}{ext}")
        export_pending_list(contracts, pending_path)
        paths.append(pending_path)

        expiring_path = str(Path(out_dir) / f"到期清单_{days}天_{timestamp}{ext}")
        export_expiring_list(contracts, expiring_path, days)
        paths.append(expiring_path)

        summary_path = str(Path(out_dir) / f"合同摘要_{timestamp}{ext}")
        export_contract_summary(contracts, summary_path)
        paths.append(summary_path)

        progress_path = str(Path(out_dir) / f"处理进度表_{timestamp}{ext}")
        export_review_progress(contracts, progress_path)
        paths.append(progress_path)

        console.print("[bold green]✅ 所有报表已导出:[/bold green]")
        for p in paths:
            console.print(f"   📄 {p}")
        console.print(f"   共 {len(contracts)} 份合同数据")
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
