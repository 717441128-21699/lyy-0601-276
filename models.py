from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Optional
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


class Contract(BaseModel):
    contract_id: str = ""
    file_path: str
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

    @property
    def is_valid(self) -> bool:
        return all(issue.risk_level != RiskLevel.HIGH for issue in self.issues)

    @property
    def risk_level(self) -> RiskLevel:
        if any(issue.risk_level == RiskLevel.HIGH for issue in self.issues):
            return RiskLevel.HIGH
        if any(issue.risk_level == RiskLevel.MEDIUM for issue in self.issues):
            return RiskLevel.MEDIUM
        if self.issues:
            return RiskLevel.LOW
        return RiskLevel.LOW

    def add_issue(self, issue: Issue) -> None:
        self.issues.append(issue)


class ContractDatabase(BaseModel):
    contracts: List[Contract] = Field(default_factory=list)
    last_scan_time: Optional[str] = None
