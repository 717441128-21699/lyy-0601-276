from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Tuple

from models import Contract, Issue, IssueType, RiskLevel


def validate_id_number(id_number: str) -> bool:
    if not id_number:
        return False
    id_number = id_number.strip().upper()
    if len(id_number) not in (15, 18):
        return False
    if len(id_number) == 18:
        if not re.match(r"^\d{17}[\dX]$", id_number):
            return False
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        check_codes = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]
        total = sum(int(id_number[i]) * weights[i] for i in range(17))
        if check_codes[total % 11] != id_number[17]:
            return False
    else:
        if not re.match(r"^\d{15}$", id_number):
            return False
    return True


def check_missing_signatures(contract: Contract) -> List[Issue]:
    issues: List[Issue] = []
    missing: List[str] = []
    if not contract.has_tenant_signature:
        missing.append("承租方(租客)")
    if not contract.has_landlord_signature:
        missing.append("出租方(房东)")
    if missing:
        issues.append(Issue(
            issue_type=IssueType.MISSING_SIGNATURE,
            description=f"缺少签名: {', '.join(missing)}",
            risk_level=RiskLevel.HIGH,
            suggestion=f"请联系{', '.join(missing)}补签合同",
        ))
    return issues


def check_date_conflicts(contract: Contract) -> List[Issue]:
    issues: List[Issue] = []
    if contract.start_date and contract.end_date:
        if contract.end_date <= contract.start_date:
            issues.append(Issue(
                issue_type=IssueType.DATE_CONFLICT,
                description=f"租期日期冲突: 结束日期({contract.end_date})早于或等于开始日期({contract.start_date})",
                risk_level=RiskLevel.HIGH,
                suggestion="请核对并修正租期的开始和结束日期",
            ))
    if contract.sign_date and contract.start_date:
        if contract.sign_date > contract.start_date:
            issues.append(Issue(
                issue_type=IssueType.DATE_CONFLICT,
                description=f"签署日期({contract.sign_date})晚于租期开始日期({contract.start_date})",
                risk_level=RiskLevel.MEDIUM,
                suggestion="请确认签署日期是否正确，如为补签请注明",
            ))
    return issues


def check_lease_overlap(contracts: List[Contract]) -> Dict[str, List[Issue]]:
    overlap_issues: Dict[str, List[Issue]] = {}
    room_contracts: Dict[str, List[Contract]] = {}

    for c in contracts:
        if c.room_number:
            room_contracts.setdefault(c.room_number, []).append(c)

    for room, room_c_list in room_contracts.items():
        valid_contracts = [c for c in room_c_list if c.start_date and c.end_date]
        for i in range(len(valid_contracts)):
            for j in range(i + 1, len(valid_contracts)):
                c1, c2 = valid_contracts[i], valid_contracts[j]
                if c1.start_date < c2.end_date and c2.start_date < c1.end_date:
                    issue1 = Issue(
                        issue_type=IssueType.LEASE_OVERLAP,
                        description=f"房源[{room}]租期重叠: 与合同[{c2.contract_id or c2.file_path}]租期重叠 "
                                    f"({c2.start_date} ~ {c2.end_date})",
                        risk_level=RiskLevel.HIGH,
                        suggestion="请核实该房源是否同时租给多方，及时处理一房多租问题",
                    )
                    issue2 = Issue(
                        issue_type=IssueType.LEASE_OVERLAP,
                        description=f"房源[{room}]租期重叠: 与合同[{c1.contract_id or c1.file_path}]租期重叠 "
                                    f"({c1.start_date} ~ {c1.end_date})",
                        risk_level=RiskLevel.HIGH,
                        suggestion="请核实该房源是否同时租给多方，及时处理一房多租问题",
                    )
                    overlap_issues.setdefault(c1.contract_id or c1.file_path, []).append(issue1)
                    overlap_issues.setdefault(c2.contract_id or c2.file_path, []).append(issue2)

    return overlap_issues


def check_rent_abnormal(contract: Contract, all_contracts: List[Contract]) -> List[Issue]:
    issues: List[Issue] = []
    if contract.monthly_rent <= 0:
        issues.append(Issue(
            issue_type=IssueType.ABNORMAL_RENT,
            description="租金金额缺失或为0",
            risk_level=RiskLevel.HIGH,
            suggestion="请填写正确的月租金金额",
        ))
        return issues

    same_room_rents = [
        c.monthly_rent for c in all_contracts
        if c.room_number == contract.room_number and c.monthly_rent > 0 and c != contract
    ]

    if not same_room_rents:
        return issues

    avg_rent = sum(same_room_rents) / len(same_room_rents)
    if avg_rent > 0:
        deviation = abs(contract.monthly_rent - avg_rent) / avg_rent
        if deviation > 0.5:
            issues.append(Issue(
                issue_type=IssueType.ABNORMAL_RENT,
                description=f"租金异常偏高/偏低: 月租金{contract.monthly_rent:.0f}元, "
                            f"同房源平均租金{avg_rent:.0f}元, 偏离{deviation*100:.1f}%",
                risk_level=RiskLevel.MEDIUM,
                suggestion="请核实租金金额是否正确，确认是否有特殊约定",
            ))
    return issues


def check_deposit_mismatch(contract: Contract) -> List[Issue]:
    issues: List[Issue] = []
    if contract.deposit <= 0:
        issues.append(Issue(
            issue_type=IssueType.DEPOSIT_MISMATCH,
            description="押金金额缺失或为0",
            risk_level=RiskLevel.HIGH,
            suggestion="请填写正确的押金金额",
        ))
        return issues

    if contract.monthly_rent > 0:
        ratio = contract.deposit / contract.monthly_rent
        common_ratios = [1.0, 2.0, 3.0, 0.5]
        matched = any(abs(ratio - r) < 0.1 for r in common_ratios)
        if not matched:
            issues.append(Issue(
                issue_type=IssueType.DEPOSIT_MISMATCH,
                description=f"押金金额异常: 押金{contract.deposit:.0f}元, "
                            f"月租金{contract.monthly_rent:.0f}元, "
                            f"押金/租金比为{ratio:.2f}(常见为0.5/1/2/3)",
                risk_level=RiskLevel.LOW,
                suggestion="请确认押金金额是否正确，是否有特殊约定",
            ))
    return issues


def check_id_number_format(contract: Contract) -> List[Issue]:
    issues: List[Issue] = []
    if contract.tenant_id_number:
        if not validate_id_number(contract.tenant_id_number):
            issues.append(Issue(
                issue_type=IssueType.INVALID_ID_NUMBER,
                description=f"承租方身份证号格式错误: {contract.tenant_id_number}",
                risk_level=RiskLevel.HIGH,
                suggestion="请核实承租方身份证号并重新填写正确的18位身份证号码",
            ))
    else:
        issues.append(Issue(
            issue_type=IssueType.INVALID_ID_NUMBER,
            description="承租方身份证号缺失",
            risk_level=RiskLevel.HIGH,
            suggestion="请补充承租方身份证号码",
        ))

    if contract.landlord_id_number and not validate_id_number(contract.landlord_id_number):
        issues.append(Issue(
            issue_type=IssueType.INVALID_ID_NUMBER,
            description=f"出租方身份证号格式错误: {contract.landlord_id_number}",
            risk_level=RiskLevel.MEDIUM,
            suggestion="请核实出租方身份证号并重新填写",
        ))

    return issues


def check_single_contract(contract: Contract, all_contracts: List[Contract]) -> List[Issue]:
    all_issues: List[Issue] = []
    all_issues.extend(check_missing_signatures(contract))
    all_issues.extend(check_date_conflicts(contract))
    all_issues.extend(check_rent_abnormal(contract, all_contracts))
    all_issues.extend(check_deposit_mismatch(contract))
    all_issues.extend(check_id_number_format(contract))
    return all_issues


def check_all_contracts(contracts: List[Contract]) -> List[Contract]:
    for contract in contracts:
        contract.issues = check_single_contract(contract, contracts)

    overlap_map = check_lease_overlap(contracts)
    for contract in contracts:
        key = contract.contract_id or contract.file_path
        if key in overlap_map:
            contract.issues.extend(overlap_map[key])

    return contracts
