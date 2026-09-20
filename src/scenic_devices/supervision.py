"""文旅智能设备试点监管的领域模型。

型号档案由厂商维护，试运行申请由景区提交，审查结论、批准证书、
部署、事故处置与复核记录共同构成从一次部署回到证据与责任人的链条。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class ReviewDimension(str, Enum):
    """必须全部出具结论的四个审查维度，可并行开展。"""

    TECHNICAL = "technical"
    ACCESSIBILITY = "accessibility"
    SAFETY = "safety"
    DATA_PROTECTION = "data_protection"


class ReviewOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class Severity(str, Enum):
    """事故、投诉与抽检异常的严重度，对应三级处置。"""

    MINOR = "minor"  # 单点暂停
    SERIOUS = "serious"  # 同型号排查
    CRITICAL = "critical"  # 全面撤销


class IncidentKind(str, Enum):
    ACCIDENT = "accident"
    COMPLAINT = "complaint"
    SPOT_CHECK = "spot_check"


class ModelStatus(str, Enum):
    ACTIVE = "active"
    UNDER_INVESTIGATION = "under_investigation"
    REVOKED = "revoked"


class ApplicationStatus(str, Enum):
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class CertificateStatus(str, Enum):
    VALID = "valid"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"  # 被变更申请的新证书取代


class DeploymentStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class ChangeReason(str, Enum):
    """三类必须重新申请、不得套用旧证书的变更。"""

    FIRMWARE_UPGRADE = "firmware_upgrade"
    PART_REPLACEMENT = "part_replacement"
    SCOPE_EXPANSION = "scope_expansion"


@dataclass(frozen=True)
class Evidence:
    """安全测试、隐私评估、维护方案等支撑材料，带有效期。"""

    evidence_id: str
    kind: str
    summary: str
    issued_on: date
    valid_until: date
    confidential: bool = True

    def is_valid_on(self, day: date) -> bool:
        return self.issued_on <= day <= self.valid_until


@dataclass
class ModelDossier:
    """厂商按型号维护的档案。传感器、维护方案等属商业秘密，不进入公众视图。"""

    model_code: str
    manufacturer: str
    device_class: str  # 对应 registry 中的设备类型编码
    capability_boundary: tuple[str, ...]
    firmware_versions: tuple[str, ...]
    hardware_revisions: tuple[str, ...]
    sensors: tuple[str, ...]
    privacy_processing: str
    maintenance_plan: str
    risk_notices: tuple[str, ...]  # 面向公众的风险提示
    evidence: dict[str, Evidence] = field(default_factory=dict)
    status: ModelStatus = ModelStatus.ACTIVE


@dataclass(frozen=True)
class ReviewConclusion:
    """单一维度的审查结论，记录责任人与所依据的证据。"""

    dimension: ReviewDimension
    outcome: ReviewOutcome
    reviewer: str
    decided_on: date
    evidence_ids: tuple[str, ...]


@dataclass
class TrialApplication:
    """景区结合地形、客流与人员配置提交的限定范围试运行申请。"""

    application_id: str
    model_code: str
    firmware_version: str
    hardware_revision: str
    scenic_area: str
    terrain: str
    visitor_flow: int
    staffing: int
    scenarios: tuple[str, ...]
    max_visitors: int
    reviews: dict[ReviewDimension, ReviewConclusion] = field(default_factory=dict)
    status: ApplicationStatus = ApplicationStatus.IN_REVIEW
    change_reason: ChangeReason | None = None
    replaces_certificate: str | None = None


@dataclass
class Certificate:
    """批准记录：写明适用场景、人数上限与复评日期，并锁定固件与硬件版本。"""

    certificate_id: str
    application_id: str
    model_code: str
    firmware_version: str
    hardware_revision: str
    scenic_area: str
    scenarios: tuple[str, ...]
    max_visitors: int
    issued_on: date
    review_by: date
    status: CertificateStatus = CertificateStatus.VALID


@dataclass
class Deployment:
    """景区在证书限定范围内的一次实际部署。"""

    deployment_id: str
    certificate_id: str
    model_code: str
    scenic_area: str
    firmware_version: str
    started_on: date
    status: DeploymentStatus = DeploymentStatus.ACTIVE


@dataclass(frozen=True)
class Incident:
    incident_id: str
    kind: IncidentKind
    severity: Severity
    model_code: str
    occurred_on: date
    detail: str
    deployment_id: str | None = None  # 单点暂停必须指明部署


@dataclass(frozen=True)
class ReReview:
    """整改后的复核记录，是恢复运行的唯一依据。"""

    reviewer: str
    decided_on: date
    notes: str


@dataclass(frozen=True)
class PublicModelView:
    """公众查询视图：只含适用范围与风险提示，不含商业秘密。"""

    model_code: str
    device_class: str
    manufacturer: str
    status: str
    scenarios: tuple[str, ...]
    max_visitors: int | None
    review_by: date | None
    risk_notices: tuple[str, ...]
