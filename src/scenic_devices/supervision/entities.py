"""文旅智能设备试点监管的领域实体。

厂商按型号维护档案，景区按限定范围申请试运行，
审查、批准、部署、事件处置与复核恢复均围绕这些实体展开。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class ModelStatus(StrEnum):
    """型号档案状态；景区只能选用“有效”状态的型号。"""

    ACTIVE = "有效"
    UNDER_INVESTIGATION = "排查中"
    REVOKED = "已撤销"


class EvidenceKind(StrEnum):
    """厂商证据材料类型。"""

    SAFETY_TEST = "安全测试"
    PRIVACY_PROCESSING = "隐私处理"
    MAINTENANCE_PLAN = "维护方案"
    ACCESSIBILITY = "无障碍评估"


#: 型号档案必须齐备的证据类型
REQUIRED_EVIDENCE_KINDS: tuple[EvidenceKind, ...] = (
    EvidenceKind.SAFETY_TEST,
    EvidenceKind.PRIVACY_PROCESSING,
    EvidenceKind.MAINTENANCE_PLAN,
)


@dataclass(frozen=True)
class Evidence:
    """证据材料：带有效期，内容属商业秘密，不向公众开放。"""

    evidence_id: str
    kind: EvidenceKind
    title: str
    issuer: str
    issued_on: date
    valid_until: date

    def is_valid_on(self, day: date) -> bool:
        """判断证据在某日期是否仍处有效期内。"""
        return self.issued_on <= day <= self.valid_until


@dataclass(frozen=True)
class SoftwareVersion:
    """型号登记的软件（固件）版本。"""

    version: str
    released_on: date
    summary: str = ""


@dataclass(frozen=True)
class Sensor:
    """设备传感器。"""

    name: str
    purpose: str = ""


@dataclass(frozen=True)
class CapabilityBoundary:
    """能力边界：声明功能不得超出所属设备类型的能力。"""

    functions: tuple[str, ...]
    max_speed_kmh: float | None = None
    forbidden_terrain: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class MaintenancePlan:
    """维护方案。"""

    summary: str
    interval_days: int
    covers_staff_handover: bool = False


@dataclass
class DeviceModel:
    """厂商按型号维护的档案。"""

    model_code: str
    manufacturer: str
    device_class: str
    capability_boundary: CapabilityBoundary
    privacy_processing: str
    maintenance_plan: MaintenancePlan
    sensors: tuple[Sensor, ...] = ()
    risk_notices: tuple[str, ...] = ()
    software_versions: dict[str, SoftwareVersion] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    status: ModelStatus = ModelStatus.ACTIVE

    def evidence_kinds(self) -> set[EvidenceKind]:
        """档案中已具备的证据类型。"""
        return {item.kind for item in self.evidence.values()}


class ChangeType(StrEnum):
    """申请类型；除首次外均为变更申请，必须基于旧批准记录另行申请。"""

    INITIAL = "首次申请"
    FIRMWARE_UPGRADE = "固件升级"
    PARTS_REPLACEMENT = "关键零件更换"
    SCOPE_EXPANSION = "扩大使用范围"


class ApplicationStatus(StrEnum):
    PENDING = "待审查"
    APPROVED = "已批准"


@dataclass(frozen=True)
class TrialScope:
    """限定范围：景区结合地形、客流与人员配置申报。"""

    zones: tuple[str, ...]
    terrain: str
    expected_daily_visitors: int
    on_site_staff: int
    certified_operators: int
    requested_headcount: int


class ReviewDimension(StrEnum):
    """四类可并行开展的审查。"""

    TECHNICAL = "技术"
    ACCESSIBILITY = "无障碍"
    SAFETY = "安全"
    DATA_PROTECTION = "数据保护"


@dataclass(frozen=True)
class Review:
    """单个维度的审查结论，记录审查责任人。"""

    dimension: ReviewDimension
    reviewer: str
    passed: bool
    decided_on: date
    comment: str = ""


@dataclass
class TrialApplication:
    """景区提交的试运行申请。"""

    application_id: str
    scenic_area: str
    model_code: str
    software_version: str
    change_type: ChangeType
    scope: TrialScope
    submitted_on: date
    supersedes: str | None = None
    part_changes: tuple[str, ...] = ()
    status: ApplicationStatus = ApplicationStatus.PENDING
    reviews: dict[ReviewDimension, Review] = field(default_factory=dict)


class ApprovalStatus(StrEnum):
    ACTIVE = "有效"
    SUSPENDED = "已暂停"
    REVOKED = "已撤销"


@dataclass
class Approval:
    """批准记录：写明适用场景、人数上限和复评日期。"""

    approval_no: str
    application_id: str
    scenic_area: str
    model_code: str
    software_version: str
    scenarios: tuple[str, ...]
    headcount_limit: int
    review_date: date
    issued_on: date
    status: ApprovalStatus = ApprovalStatus.ACTIVE


class DeploymentStatus(StrEnum):
    ACTIVE = "运行中"
    SUSPENDED = "已暂停"
    TERMINATED = "已终止"


@dataclass
class Deployment:
    """一次部署：一台设备在某个批准记录下投入运行。"""

    deployment_id: str
    approval_no: str
    unit_serial: str
    zone: str
    firmware_version: str
    started_on: date
    status: DeploymentStatus = DeploymentStatus.ACTIVE


class IncidentKind(StrEnum):
    ACCIDENT = "事故"
    COMPLAINT = "投诉"
    INSPECTION = "抽检异常"


class Severity(StrEnum):
    """严重度，决定触发措施。"""

    MINOR = "一般"
    SERIOUS = "严重"
    CRITICAL = "特别严重"


class IncidentStatus(StrEnum):
    OPEN = "待复核"
    RESOLVED = "已复核"


_SEVERITY_ACTIONS: dict[Severity, str] = {
    Severity.MINOR: "单点暂停",
    Severity.SERIOUS: "同型号排查",
    Severity.CRITICAL: "全面撤销",
}


@dataclass
class Incident:
    """事故、投诉或抽检异常事件。"""

    incident_id: str
    kind: IncidentKind
    severity: Severity
    deployment_id: str
    model_code: str
    reported_on: date
    description: str
    affected_deployments: tuple[str, ...]
    status: IncidentStatus = IncidentStatus.OPEN

    @property
    def action(self) -> str:
        """严重度对应的处置措施。"""
        return _SEVERITY_ACTIONS[self.severity]


@dataclass(frozen=True)
class ReReview:
    """整改后的复核记录；恢复只能来自有记录的复核。"""

    incident_id: str
    reviewer: str
    passed: bool
    decided_on: date
    notes: str = ""
