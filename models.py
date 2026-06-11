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


class PaymentMethod(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    OTHER = "other"


class Issue(BaseModel):
    issue_type: IssueType
    description: str
    risk_level: RiskLevel
    suggestion: str = ""
    status: IssueStatus = IssueStatus.PENDING
    review_note: str = ""
    review_time: Optional[str] = None

    def mark_status(self, status: IssueStatus, note: str = "") -> None:
        self.status = status
        self.review_note = note
        self.review_time = datetime.now().isoformat()


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
