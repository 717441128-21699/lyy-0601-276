from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

from models import Contract, PaymentMethod, ChangeRiskLevel


def parse_date(date_str: str) -> Optional[date]:
    date_str = date_str.strip()
    patterns = [
        r"(\d{4})[\-/.年](\d{1,2})[\-/.月](\d{1,2})",
        r"(\d{4})(\d{2})(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, date_str)
        if match:
            try:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                    return date(year, month, day)
            except (ValueError, TypeError):
                pass
    return None


def parse_amount(amount_str: str) -> float:
    amount_str = amount_str.strip().replace(",", "").replace("，", "")
    num_match = re.search(r"([\d.]+)", amount_str)
    if num_match:
        try:
            val = float(num_match.group(1))
            if val > 0:
                return val
        except ValueError:
            return 0.0
    return 0.0


def detect_payment_method(text: str) -> PaymentMethod:
    if any(k in text for k in ["押一付一", "月付", "每月支付", "按月支付"]):
        return PaymentMethod.MONTHLY
    if any(k in text for k in ["押一付三", "季付", "每季度", "按季度", "季度"]):
        return PaymentMethod.QUARTERLY
    if any(k in text for k in ["押一付六", "半年付", "每半年"]):
        return PaymentMethod.SEMI_ANNUAL
    if any(k in text for k in ["年付", "每年支付", "按年", "一年一付"]):
        return PaymentMethod.ANNUAL
    return PaymentMethod.OTHER


def clean_text(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^[：:]\s*", "", s)
    s = re.sub(r"^[\s（）()\[\]【】]+", "", s)
    s = re.sub(r"[\s（）()\[\]【】]+$", "", s)
    return s.strip()


def extract_room_number(text: str) -> str:
    patterns = [
        r"房号\s*[：:]\s*([^\n\r，。；,;]{1,80})",
        r"房屋地址\s*[：:]\s*([^\n\r，。；,;]{1,80})",
        r"房屋位置\s*[：:]\s*([^\n\r，。；,;]{1,80})",
        r"地址\s*[：:]\s*([^\n\r，。；,;]{1,80})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = clean_text(m.group(1))
            if val and len(val) >= 2:
                return val[:80]

    room_match = re.search(r"(\d+\s*号楼\s*\d+\s*单元\s*\d+\s*室)", text)
    if room_match:
        return room_match.group(1)

    room_match2 = re.search(r"([A-Za-z]?\d+\s*[栋号楼幢]\s*\d*\s*单元?\s*\d+\s*[室号房]\d*)", text)
    if room_match2:
        return room_match2.group(0)

    return ""


def extract_tenant_info(text: str) -> Tuple[str, str]:
    name = ""
    id_number = ""

    name_patterns = [
        r"乙方[（(]承租方[)）]?\s*[：:]\s*姓名\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"承租方[（(]乙方[)）]?\s*[：:]\s*姓名\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"乙方[（(]承租方[)）]?\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"承租方[（(]乙方[)）]?\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"乙方\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"承租方\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"承租人\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"租客\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
    ]
    for p in name_patterns:
        m = re.search(p, text)
        if m:
            name = clean_text(m.group(1))
            if name and 2 <= len(name) <= 20:
                break

    id_patterns = [
        r"(?:乙方|承租方|承租人|租客).{0,100}?身份证[号号码]{0,3}\s*[：:]\s*([0-9Xx]{15,18})",
    ]
    for p in id_patterns:
        m = re.search(p, text, re.DOTALL)
        if m:
            id_number = m.group(1).strip().upper()
            break

    return name, id_number


def extract_landlord_info(text: str) -> Tuple[str, str]:
    name = ""
    id_number = ""

    name_patterns = [
        r"甲方[（(]出租方[)）]?\s*[：:]\s*姓名\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"出租方[（(]甲方[)）]?\s*[：:]\s*姓名\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"甲方[（(]出租方[)）]?\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"出租方[（(]甲方[)）]?\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"甲方\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"出租方\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"房东\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"业主\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
    ]
    for p in name_patterns:
        m = re.search(p, text)
        if m:
            name = clean_text(m.group(1))
            if name and 2 <= len(name) <= 20:
                break

    id_patterns = [
        r"(?:甲方|出租方|房东|业主).{0,100}?身份证[号号码]{0,3}\s*[：:]\s*([0-9Xx]{15,18})",
    ]
    for p in id_patterns:
        m = re.search(p, text, re.DOTALL)
        if m:
            id_number = m.group(1).strip().upper()
            break

    return name, id_number


def extract_lease_dates(text: str) -> Tuple[Optional[date], Optional[date]]:
    start_date = None
    end_date = None

    patterns = [
        r"(?:租赁期限|租期|合同期限).{0,10}?自\s*([0-9年月日\-/.]{6,20})\s*(?:至|到|—|-|〜)\s*([0-9年月日\-/.]{6,20})",
        r"自\s*([0-9年月日\-/.]{6,20})\s*(?:起)?\s*(?:至|到|—|-)\s*([0-9年月日\-/.]{6,20})\s*止",
    ]
    for p in patterns:
        m = re.search(p, text, re.DOTALL)
        if m:
            start_date = parse_date(m.group(1))
            end_date = parse_date(m.group(2))
            if start_date and end_date:
                return start_date, end_date

    if not start_date:
        for p in [r"起租[日日期]{0,3}\s*[：:]\s*([0-9年月日\-/.]{6,20})", r"开始日期\s*[：:]\s*([0-9年月日\-/.]{6,20})"]:
            m = re.search(p, text)
            if m:
                d = parse_date(m.group(1))
                if d:
                    start_date = d
                    break

    if not end_date:
        for p in [r"到期[日日期]{0,3}\s*[：:]\s*([0-9年月日\-/.]{6,20})", r"结束日期\s*[：:]\s*([0-9年月日\-/.]{6,20})", r"终止日期\s*[：:]\s*([0-9年月日\-/.]{6,20})"]:
            m = re.search(p, text)
            if m:
                d = parse_date(m.group(1))
                if d:
                    end_date = d
                    break

    return start_date, end_date


def extract_rent_and_deposit(text: str) -> Tuple[float, float]:
    rent = 0.0
    deposit = 0.0

    rent_patterns = [
        r"月租金\s*[为是]?\s*[：:]?\s*(?:人民币)?\s*[￥¥]?\s*([\d,，.]+)\s*元",
        r"每月租金\s*[为是]?\s*[：:]?\s*(?:人民币)?\s*[￥¥]?\s*([\d,，.]+)\s*元",
        r"租金\s*每月\s*[为是]?\s*[：:]?\s*(?:人民币)?\s*[￥¥]?\s*([\d,，.]+)\s*元",
        r"租金\s*[为是]?\s*[：:]?\s*(?:人民币)?\s*[￥¥]?\s*([\d,，.]+)\s*元\s*/\s*月",
    ]
    for p in rent_patterns:
        m = re.search(p, text)
        if m:
            r = parse_amount(m.group(1))
            if r > 0:
                rent = r
                break

    deposit_patterns = [
        r"押金\s*[为是]?\s*[：:]?\s*(?:人民币)?\s*[￥¥]?\s*([\d,，.]+)\s*元",
        r"保证金\s*[为是]?\s*[：:]?\s*(?:人民币)?\s*[￥¥]?\s*([\d,，.]+)\s*元",
    ]
    for p in deposit_patterns:
        m = re.search(p, text)
        if m:
            d = parse_amount(m.group(1))
            if d > 0:
                deposit = d
                break

    if deposit == 0:
        m = re.search(r"押\s*([一二三四五六七八九十\d]+)\s*(?:付|押)", text)
        if m and rent > 0:
            num_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            k = m.group(1)
            multiplier = num_map.get(k)
            if multiplier:
                deposit = rent * multiplier
            elif k.isdigit():
                deposit = rent * int(k)

    return rent, deposit


def extract_agent_name(text: str) -> str:
    patterns = [
        r"居间方[（(]经纪人?[)）]?\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"经纪人\s*[姓名：:\s]*([^\n\r，。；,;（(]{2,20})",
        r"经办人\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"中介\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
        r"居间方\s*[：:]\s*([^\n\r，。；,;（(]{2,20})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = clean_text(m.group(1))
            if val and 2 <= len(val) <= 20:
                return val
    return ""


def extract_sign_date(text: str) -> Optional[date]:
    patterns = [
        r"(?:签订日期|签约日期|签署日期|签订时间)\s*[：:]\s*([0-9年月日\-/.]{6,20})",
        r"本合同签订于\s*([0-9年月日\-/.]{6,20})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            d = parse_date(m.group(1))
            if d:
                return d
    return None


def detect_signatures(text: str) -> Tuple[bool, bool, bool]:
    has_tenant = False
    has_landlord = False
    has_agent = False

    lines = text.split("\n")

    tenant_patterns = [
        r"乙方.*?签字[：:]\s*(\S{2,20})",
        r"承租方.*?签字[：:]\s*(\S{2,20})",
        r"承租人.*?签字[：:]\s*(\S{2,20})",
    ]
    landlord_patterns = [
        r"甲方.*?签字[：:]\s*(\S{2,20})",
        r"出租方.*?签字[：:]\s*(\S{2,20})",
    ]
    agent_patterns = [
        r"居间方.*?签字[：:]\s*(\S{2,20})",
        r"经纪人.*?签字[：:]\s*(\S{2,20})",
        r"中介.*?签字[：:]\s*(\S{2,20})",
    ]

    for line in lines:
        stripped = line.strip()
        for p in tenant_patterns:
            m = re.search(p, stripped)
            if m:
                name = m.group(1).strip("：: ")
                if name and len(name) >= 2:
                    has_tenant = True
        for p in landlord_patterns:
            m = re.search(p, stripped)
            if m:
                name = m.group(1).strip("：: ")
                if name and len(name) >= 2:
                    has_landlord = True
        for p in agent_patterns:
            m = re.search(p, stripped)
            if m:
                name = m.group(1).strip("：: ")
                if name and len(name) >= 2:
                    has_agent = True

    return has_tenant, has_landlord, has_agent


def scan_contract_file(file_path: str) -> Contract:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    file_mtime = os.path.getmtime(file_path)
    contract = Contract(file_path=file_path, file_mtime=file_mtime)
    contract.contract_id = os.path.splitext(os.path.basename(file_path))[0]

    contract.room_number = extract_room_number(text)
    contract.tenant_name, contract.tenant_id_number = extract_tenant_info(text)
    contract.landlord_name, contract.landlord_id_number = extract_landlord_info(text)
    contract.start_date, contract.end_date = extract_lease_dates(text)
    contract.monthly_rent, contract.deposit = extract_rent_and_deposit(text)
    contract.payment_method = detect_payment_method(text)
    contract.agent_name = extract_agent_name(text)
    contract.sign_date = extract_sign_date(text)
    contract.has_tenant_signature, contract.has_landlord_signature, contract.has_agent_signature = detect_signatures(text)

    return contract


def collect_files(folder_path: str, recursive: bool = False) -> List[Path]:
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"文件夹不存在: {folder_path}")

    supported_extensions = {".txt", ".md"}
    files: List[Path] = []

    if recursive:
        for root, _, filenames in os.walk(folder):
            for fname in filenames:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in supported_extensions:
                    files.append(fpath)
    else:
        for fpath in folder.iterdir():
            if fpath.is_file() and fpath.suffix.lower() in supported_extensions:
                files.append(fpath)

    return sorted(files)


class ScanResult:
    def __init__(self):
        self.new_contracts: List[Contract] = []
        self.updated_contracts: List[Contract] = []
        self.unchanged_contracts: List[Contract] = []
        self.errors: List[tuple] = []

    @property
    def all_contracts(self) -> List[Contract]:
        return self.new_contracts + self.updated_contracts + self.unchanged_contracts

    @property
    def total_count(self) -> int:
        return len(self.all_contracts)

    @property
    def new_count(self) -> int:
        return len(self.new_contracts)

    @property
    def updated_count(self) -> int:
        return len(self.updated_contracts)

    @property
    def unchanged_count(self) -> int:
        return len(self.unchanged_contracts)


def assess_change_risk(field_name: str, old_val: str, new_val: str) -> Tuple[ChangeRiskLevel, str]:
    risk = ChangeRiskLevel.NONE
    note = ""

    if field_name == "月租金":
        try:
            old_f = float(old_val)
            new_f = float(new_val)
            if old_f > 0:
                change_pct = abs(new_f - old_f) / old_f
                if change_pct >= 0.3:
                    risk = ChangeRiskLevel.HIGH
                    note = f"租金变动{change_pct*100:.0f}%，超过30%阈值"
                elif change_pct >= 0.1:
                    risk = ChangeRiskLevel.MEDIUM
                    note = f"租金变动{change_pct*100:.0f}%"
        except Exception:
            pass
    elif field_name == "押金":
        try:
            old_f = float(old_val)
            new_f = float(new_val)
            if old_f > 0:
                change_pct = abs(new_f - old_f) / old_f
                if change_pct >= 0.5:
                    risk = ChangeRiskLevel.HIGH
                    note = f"押金变动{change_pct*100:.0f}%，超过50%阈值"
                elif change_pct >= 0.2:
                    risk = ChangeRiskLevel.MEDIUM
                    note = f"押金变动{change_pct*100:.0f}%"
        except Exception:
            pass
    elif "签名" in field_name:
        if old_val == "True" and new_val == "False":
            risk = ChangeRiskLevel.HIGH
            note = f"{field_name}从有变为无，需确认是否丢失签名"
    elif field_name in ("租期开始", "租期结束"):
        try:
            old_d = date.fromisoformat(old_val)
            new_d = date.fromisoformat(new_val)
            if field_name == "租期结束" and new_d < old_d:
                days = (old_d - new_d).days
                risk = ChangeRiskLevel.HIGH
                note = f"租期缩短{days}天，需确认是否提前解约"
        except Exception:
            pass
    elif field_name == "租客姓名":
        if old_val and new_val and old_val != new_val:
            risk = ChangeRiskLevel.HIGH
            note = f"租客变更：{old_val} → {new_val}，需确认转租手续"
    elif field_name == "房号":
        if old_val and new_val and old_val != new_val:
            risk = ChangeRiskLevel.HIGH
            note = f"房号变更：{old_val} → {new_val}，需确认合同是否对应正确房源"

    return risk, note


def compare_and_merge_changes(old: Contract, new: Contract) -> None:
    compare_fields = [
        ("room_number", "房号"),
        ("tenant_name", "租客姓名"),
        ("tenant_id_number", "租客身份证"),
        ("landlord_name", "房东姓名"),
        ("landlord_id_number", "房东身份证"),
        ("start_date", "租期开始"),
        ("end_date", "租期结束"),
        ("monthly_rent", "月租金"),
        ("deposit", "押金"),
        ("payment_method", "付款方式"),
        ("agent_name", "经纪人"),
        ("has_tenant_signature", "租客签名"),
        ("has_landlord_signature", "房东签名"),
        ("has_agent_signature", "经纪人签名"),
        ("sign_date", "签署日期"),
    ]
    for attr, label in compare_fields:
        old_val = getattr(old, attr)
        new_val = getattr(new, attr)
        old_str = str(old_val)
        new_str = str(new_val)
        if isinstance(old_val, date):
            old_str = str(old_val)
        if isinstance(new_val, date):
            new_str = str(new_val)
        if old_str != new_str:
            risk, note = assess_change_risk(label, old_str, new_str)
            new.add_field_change(label, old_str, new_str, change_risk=risk, risk_note=note)

    new.issues = old.issues
    new.review_notes = old.review_notes
    new.first_scan_time = old.first_scan_time
    new.follow_ups = old.follow_ups
    new.field_changes = old.field_changes + new.field_changes


def scan_folder(
    folder_path: str,
    recursive: bool = False,
    existing_contracts: Optional[List[Contract]] = None,
    incremental: bool = True,
) -> ScanResult:
    files = collect_files(folder_path, recursive)
    result = ScanResult()

    existing_map = {}
    if existing_contracts and incremental:
        for c in existing_contracts:
            existing_map[c.file_path] = c

    for file_path in files:
        try:
            fpath_str = str(file_path)
            fstat = file_path.stat()

            if incremental and fpath_str in existing_map:
                old_contract = existing_map[fpath_str]
                if abs(fstat.st_mtime - old_contract.file_mtime) < 0.001:
                    result.unchanged_contracts.append(old_contract)
                    continue

            new_contract = scan_contract_file(fpath_str)

            if fpath_str in existing_map:
                old_contract = existing_map[fpath_str]
                compare_and_merge_changes(old_contract, new_contract)
                result.updated_contracts.append(new_contract)
            else:
                result.new_contracts.append(new_contract)

        except Exception as e:
            result.errors.append((str(file_path), str(e)))

    return result

