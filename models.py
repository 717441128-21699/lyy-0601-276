from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IssueType(str, Enum):
    MISSING_SIGNATURE = "missing_signature"
    DATE_CONFLICT = "date_conflict"
    LEASE_OVERLAP = "lease_overlap"
    ABNORMAL_RENT = "abnormal_rent"
    DEPOSIT_MISMATCH = "deposit_mismatch"
    INVALID_ID_NUMBER = "invalid_id_number"


class IssueStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class PriorityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ChangeRiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FollowUpAction(str, Enum):
    SIGN_SUPPLEMENT = "sign_supplement"
    ID_SUPPLEMENT = "id_supplement"
    RENT_ADJUST = "rent_adjust"
    DEPOSIT_ADJUST = "deposit_adjust"
    DATE_CORRECT = "date_correct"
    PHONE_CALL = "phone_call"
    WECHAT = "wechat"
    VISIT = "visit"
    OTHER = "other"


class PaymentMethod(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    OTHER = "other"


class FollowUpRecord(BaseModel):
    follow_id: str = ""
    issue_index: int = -1
    action: FollowUpAction = FollowUpAction.OTHER
    content: str = ""
    operator: str = ""
    follow_time: str = ""
    expected_date: Optional[str] = None
    next_follow_date: Optional[str] = None
    priority: PriorityLevel = PriorityLevel.MEDIUM
    completed: bool = False
    completed_date: Optional[str] = None

    @property
    def is_overdue(self) -> bool:
        if not self.expected_date or self.completed:
            return False
        try:
            exp = date.fromisoformat(self.expected_date[:10])
            return date.today() > exp
        except Exception:
            return False

    @property
    def is_due_today(self) -> bool:
        if not self.expected_date or self.completed:
            return False
        try:
            exp = date.fromisoformat(self.expected_date[:10])
            return date.today() == exp
        except Exception:
            return False


class FieldChange(BaseModel):
    field_name: str
    old_value: str = ""
    new_value: str = ""
    change_time: str = ""
    change_risk: ChangeRiskLevel = ChangeRiskLevel.NONE
    risk_note: str = ""


class Issue(BaseModel):
    issue_type: IssueType
    description: str
    risk_level: RiskLevel
    suggestion: str = ""
    status: IssueStatus = IssueStatus.PENDING
    review_note: str = ""
    review_time: Optional[str] = None
    follow_ups: List[FollowUpRecord] = Field(default_factory=list)

    def mark_status(self, status: IssueStatus, note: str = "") -> None:
        self.status = status
        self.review_note = note
        self.review_time = datetime.now().isoformat()

    def add_follow_up(self, action: FollowUpAction, content: str, operator: str = "",
                      expected_date: Optional[str] = None, next_follow_date: Optional[str] = None,
                      priority: PriorityLevel = PriorityLevel.MEDIUM,
                      completed: bool = False, completed_date: Optional[str] = None) -> FollowUpRecord:
        record = FollowUpRecord(
            follow_id=datetime.now().strftime("fu_%Y%m%d_%H%M%S_%f")[:-3],
            issue_index=-1,
            action=action,
            content=content,
            operator=operator,
            follow_time=datetime.now().isoformat(),
            expected_date=expected_date,
            next_follow_date=next_follow_date,
            priority=priority,
            completed=completed,
            completed_date=completed_date,
        )
        self.follow_ups.append(record)
        return record

    @property
    def latest_follow_up(self) -> Optional[FollowUpRecord]:
        if not self.follow_ups:
            return None
        return sorted(self.follow_ups, key=lambda x: x.follow_time, reverse=True)[0]


class RuleConfig(BaseModel):
    rule_name: str = "default"
    rent_deviation_threshold: float = 0.5
    deposit_multiples: List[float] = Field(default_factory=lambda: [0.5, 1.0, 2.0, 3.0])
    deposit_tolerance: float = 0.1
    expiring_days_default: int = 30
    high_risk_issue_types: List[IssueType] = Field(default_factory=lambda: [
        IssueType.MISSING_SIGNATURE,
        IssueType.DATE_CONFLICT,
        IssueType.LEASE_OVERLAP,
        IssueType.ABNORMAL_RENT,
        IssueType.INVALID_ID_NUMBER,
    ])
    require_agent_signature: bool = True
    min_rent_amount: float = 100.0

    def get_display_name(self) -> str:
        return {
            "default": "默认规则",
        }.get(self.rule_name, self.rule_name)


class ScanBatch(BaseModel):
    batch_id: str
    scan_time: str
    folder: str
    total_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    rule_name: str = "default"
    contract_file_paths: List[str] = Field(default_factory=list)
    contract_snapshots: List[Contract] = Field(default_factory=list)


class Contract(BaseModel):
    contract_id: str = ""
    file_path: str
    file_mtime: float = 0.0
    scan_batch_id: str = ""
    room_number: str = ""
    tenant_name: str = ""
    tenant_id_number: str = ""
    landlord_name: str = ""
    landlord_id_number: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    monthly_rent: float = 0.0
    deposit: float = 0.0
    payment_method: PaymentMethod = PaymentMethod.OTHER
    agent_name: str = ""
    has_tenant_signature: bool = False
    has_landlord_signature: bool = False
    has_agent_signature: bool = False
    sign_date: Optional[date] = None
    issues: List[Issue] = Field(default_factory=list)
    review_notes: str = ""
    first_scan_time: Optional[str] = None
    last_scan_time: Optional[str] = None
    field_changes: List[FieldChange] = Field(default_factory=list)
    follow_ups: List[FollowUpRecord] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return all(issue.risk_level != RiskLevel.HIGH for issue in self.issues)

    @property
    def risk_level(self) -> RiskLevel:
        if any(issue.risk_level == RiskLevel.HIGH and issue.status != IssueStatus.IGNORED
               for issue in self.issues):
            return RiskLevel.HIGH
        if any(issue.risk_level == RiskLevel.MEDIUM and issue.status != IssueStatus.IGNORED
               for issue in self.issues):
            return RiskLevel.MEDIUM
        pending_issues = [i for i in self.issues if i.status != IssueStatus.IGNORED]
        if pending_issues:
            return RiskLevel.LOW
        return RiskLevel.LOW

    @property
    def pending_issues_count(self) -> int:
        return sum(1 for i in self.issues if i.status == IssueStatus.PENDING)

    @property
    def resolved_issues_count(self) -> int:
        return sum(1 for i in self.issues if i.status in (IssueStatus.RESOLVED, IssueStatus.CONFIRMED))

    def add_issue(self, issue: Issue) -> None:
        self.issues.append(issue)

    def get_issues_by_type(self, issue_type: IssueType) -> List[Issue]:
        return [i for i in self.issues if i.issue_type == issue_type]

    def add_follow_up(self, action: FollowUpAction, content: str,
                      operator: str = "", issue_index: int = -1,
                      expected_date: Optional[str] = None, next_follow_date: Optional[str] = None,
                      priority: PriorityLevel = PriorityLevel.MEDIUM,
                      completed: bool = False, completed_date: Optional[str] = None) -> FollowUpRecord:
        record = FollowUpRecord(
            follow_id=datetime.now().strftime("fu_%Y%m%d_%H%M%S_%f")[:-3],
            issue_index=issue_index,
            action=action,
            content=content,
            operator=operator,
            follow_time=datetime.now().isoformat(),
            expected_date=expected_date,
            next_follow_date=next_follow_date,
            priority=priority,
            completed=completed,
            completed_date=completed_date,
        )
        if issue_index >= 0 and issue_index < len(self.issues):
            self.issues[issue_index].follow_ups.append(record)
        else:
            self.follow_ups.append(record)
        return record

    @property
    def latest_follow_up(self) -> Optional[FollowUpRecord]:
        all_follows: List[FollowUpRecord] = []
        all_follows.extend(self.follow_ups)
        for issue in self.issues:
            all_follows.extend(issue.follow_ups)
        if not all_follows:
            return None
        return sorted(all_follows, key=lambda x: x.follow_time, reverse=True)[0]

    @property
    def pending_follow_ups(self) -> List[FollowUpRecord]:
        all_follows: List[FollowUpRecord] = []
        all_follows.extend(self.follow_ups)
        for issue in self.issues:
            all_follows.extend(issue.follow_ups)
        return [f for f in all_follows if not f.completed]

    @property
    def overdue_follow_ups(self) -> List[FollowUpRecord]:
        return [f for f in self.pending_follow_ups if f.is_overdue]

    @property
    def due_today_follow_ups(self) -> List[FollowUpRecord]:
        return [f for f in self.pending_follow_ups if f.is_due_today]

    @property
    def high_risk_changes(self) -> List[FieldChange]:
        return [fc for fc in self.field_changes if fc.change_risk in (ChangeRiskLevel.HIGH, ChangeRiskLevel.MEDIUM)]

    def add_field_change(self, field_name: str, old_val: str, new_val: str,
                         change_risk: ChangeRiskLevel = ChangeRiskLevel.NONE,
                         risk_note: str = "") -> None:
        if str(old_val) == str(new_val):
            return
        self.field_changes.append(FieldChange(
            field_name=field_name,
            old_value=str(old_val),
            new_value=str(new_val),
            change_time=datetime.now().isoformat(),
            change_risk=change_risk,
            risk_note=risk_note,
        ))


class ContractDatabase(BaseModel):
    contracts: List[Contract] = Field(default_factory=list)
    batches: List[ScanBatch] = Field(default_factory=list)
    last_scan_time: Optional[str] = None
    current_rule: RuleConfig = Field(default_factory=RuleConfig)

    def get_contract_by_id(self, contract_id: str) -> Optional[Contract]:
        for c in self.contracts:
            if c.contract_id == contract_id:
                return c
        return None

    def get_contract_by_path(self, file_path: str) -> Optional[Contract]:
        for c in self.contracts:
            if c.file_path == file_path:
                return c
        return None

    def get_batch_by_id(self, batch_id: str) -> Optional[ScanBatch]:
        for b in self.batches:
            if b.batch_id == batch_id:
                return b
        return None
