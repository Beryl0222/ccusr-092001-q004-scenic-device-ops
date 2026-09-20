"""监管追溯与公众查询的视图。

追溯视图面向监管人员，包含证据与审查责任人；
公众视图不暴露商业秘密，只给出适用范围与风险提示。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ReviewTrace:
    """追溯用的审查结论与审查责任人。"""

    dimension: str
    reviewer: str
    passed: bool
    decided_on: date


@dataclass(frozen=True)
class EvidenceTrace:
    """追溯用的证据及其有效期状态。"""

    evidence_id: str
    kind: str
    title: str
    issuer: str
    valid_until: date
    still_valid: bool


@dataclass(frozen=True)
class TraceReport:
    """从一次部署回溯到批准记录、审查责任人与证据。"""

    deployment_id: str
    unit_serial: str
    zone: str
    firmware_version: str
    deployment_status: str
    approval_no: str
    approval_status: str
    scenarios: tuple[str, ...]
    headcount_limit: int
    review_date: date
    application_id: str
    change_type: str
    supersedes: str | None
    reviews: tuple[ReviewTrace, ...]
    evidence: tuple[EvidenceTrace, ...]
    incident_ids: tuple[str, ...]


@dataclass(frozen=True)
class PublicModelView:
    """公众视角的型号信息：适用范围与风险提示，不含商业秘密。"""

    model_code: str
    manufacturer: str
    device_class: str
    status: str
    scenarios: tuple[str, ...]
    risk_notices: tuple[str, ...]
    privacy_notice: str
    review_dates: tuple[date, ...]


@dataclass(frozen=True)
class PublicDeploymentView:
    """公众视角的景区在运行设备。"""

    scenic_area: str
    model_code: str
    zone: str
    risk_notices: tuple[str, ...]
    privacy_notice: str
    review_date: date
