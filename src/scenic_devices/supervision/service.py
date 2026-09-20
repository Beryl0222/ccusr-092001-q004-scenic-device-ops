"""文旅智能设备试点监管服务。

主线：型号档案 → 试运行申请 → 并行审查 → 批准记录 → 部署 →
事件处置 → 复核恢复，保证准入证书与真实部署一致。

- 型号档案接入现有设备类型与安全限制（registry.DeviceClass）；
- 技术、无障碍、安全、数据保护四类审查可并行提交，
  结论齐全且证据仍在有效期内才可批准；
- 固件升级、关键零件更换、扩大使用范围必须产生新申请，不能套用旧证书；
- 事故、投诉、抽检异常按严重度触发单点暂停、同型号排查或全面撤销，
  整改后的恢复只能来自有记录的复核。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Mapping

from ..registry import DeviceClass, load_device_classes
from .entities import (
    REQUIRED_EVIDENCE_KINDS,
    Approval,
    ApprovalStatus,
    ApplicationStatus,
    ChangeType,
    Deployment,
    DeploymentStatus,
    DeviceModel,
    Evidence,
    Incident,
    IncidentKind,
    IncidentStatus,
    ModelStatus,
    ReReview,
    Review,
    ReviewDimension,
    Severity,
    SoftwareVersion,
    TrialApplication,
    TrialScope,
)
from .views import (
    EvidenceTrace,
    PublicDeploymentView,
    PublicModelView,
    ReviewTrace,
    TraceReport,
)

_PRIVACY_NOTICES = {
    "visitor-consent": "设备可能采集影像等信息，使用前需征得游客同意",
    "minimal": "设备仅采集最少必要信息",
    "none": "设备不采集个人信息",
}
_DEFAULT_PRIVACY_NOTICE = "隐私处理方式以现场公示为准"


class RegulatoryService:
    """文旅智能设备试点监管服务。"""

    def __init__(self, device_classes: Mapping[str, DeviceClass]) -> None:
        self._classes = dict(device_classes)
        self._models: dict[str, DeviceModel] = {}
        self._applications: dict[str, TrialApplication] = {}
        self._approvals: dict[str, Approval] = {}
        self._deployments: dict[str, Deployment] = {}
        self._incidents: dict[str, Incident] = {}
        self._re_reviews: list[ReReview] = []
        self._counters = {"application": 0, "approval": 0, "deployment": 0, "incident": 0}

    @classmethod
    def from_registry(cls, path: str | Path) -> "RegulatoryService":
        """接入现有设备类型与安全限制清单。"""
        return cls(load_device_classes(path))

    # ------------------------------------------------------------------
    # 型号档案：厂商按型号维护
    # ------------------------------------------------------------------

    def register_model(self, model: DeviceModel) -> None:
        """登记型号档案，校验设备类型与安全限制。"""
        if model.model_code in self._models:
            raise ValueError(f"型号已登记：{model.model_code}")
        device_class = self._classes.get(model.device_class)
        if device_class is None:
            raise ValueError(f"设备类型未登记：{model.device_class}")
        extra = set(model.capability_boundary.functions) - set(device_class.capabilities)
        if extra:
            raise ValueError(f"能力边界超出设备类型能力：{sorted(extra)}")
        if "recording" in model.capability_boundary.functions and not model.privacy_processing:
            raise ValueError("具备影像能力的型号必须说明隐私处理方式")
        if device_class.requires_staff_handover and not model.maintenance_plan.covers_staff_handover:
            raise ValueError("设备类型要求人员交接，维护方案未覆盖交接流程")
        missing = [kind.value for kind in REQUIRED_EVIDENCE_KINDS if kind not in model.evidence_kinds()]
        if missing:
            raise ValueError(f"型号档案缺少证据：{missing}")
        self._models[model.model_code] = model

    def add_software_version(self, model_code: str, version: SoftwareVersion) -> None:
        """厂商登记新的软件（固件）版本；投入使用须另行申请。"""
        model = self._model(model_code)
        if version.version in model.software_versions:
            raise ValueError(f"软件版本已存在：{version.version}")
        model.software_versions[version.version] = version

    def add_evidence(self, model_code: str, evidence: Evidence) -> None:
        """厂商补充或续期证据材料。"""
        model = self._model(model_code)
        model.evidence[evidence.evidence_id] = evidence

    def valid_models(self) -> tuple[str, ...]:
        """当前有效型号，景区只能从中选用。"""
        return tuple(
            code for code, model in self._models.items() if model.status is ModelStatus.ACTIVE
        )

    # ------------------------------------------------------------------
    # 试运行申请与并行审查
    # ------------------------------------------------------------------

    def submit_application(
        self,
        *,
        scenic_area: str,
        model_code: str,
        software_version: str,
        scope: TrialScope,
        change_type: ChangeType = ChangeType.INITIAL,
        supersedes: str | None = None,
        part_changes: tuple[str, ...] = (),
        on: date,
    ) -> str:
        """景区结合地形、客流与人员配置申请限定范围的试运行。"""
        model = self._models.get(model_code)
        if model is None:
            raise ValueError(f"型号未登记：{model_code}")
        if model.status is not ModelStatus.ACTIVE:
            raise ValueError(f"型号当前不可选用（{model.status.value}）：{model_code}")
        if software_version not in model.software_versions:
            raise ValueError(f"软件版本未在型号档案中登记：{software_version}")
        if not scope.zones:
            raise ValueError("限定范围不能为空")
        if scope.requested_headcount < 1:
            raise ValueError("申请人数上限至少为 1")
        device_class = self._classes[model.device_class]
        if device_class.requires_staff_handover and scope.certified_operators < 1:
            raise ValueError("人员配置不满足设备交接要求")
        if change_type is not ChangeType.INITIAL:
            self._check_change_base(
                change_type, scenic_area, model_code, software_version, supersedes, part_changes
            )
        application_id = self._next_id("application", "SQ")
        self._applications[application_id] = TrialApplication(
            application_id=application_id,
            scenic_area=scenic_area,
            model_code=model_code,
            software_version=software_version,
            change_type=change_type,
            scope=scope,
            submitted_on=on,
            supersedes=supersedes,
            part_changes=part_changes,
        )
        return application_id

    def _check_change_base(
        self,
        change_type: ChangeType,
        scenic_area: str,
        model_code: str,
        software_version: str,
        supersedes: str | None,
        part_changes: tuple[str, ...],
    ) -> None:
        """变更申请必须基于本景区同型号的有效批准记录，不能套用旧证书。"""
        if supersedes is None:
            raise ValueError("变更申请必须注明被替代的批准记录")
        old = self._approvals.get(supersedes)
        if old is None:
            raise ValueError(f"被替代的批准记录不存在：{supersedes}")
        if old.scenic_area != scenic_area or old.model_code != model_code:
            raise ValueError("变更申请必须基于本景区同型号的批准记录")
        if old.status is ApprovalStatus.REVOKED:
            raise ValueError("原批准记录已撤销，不能套用，请提交首次申请")
        if change_type is ChangeType.FIRMWARE_UPGRADE and software_version == old.software_version:
            raise ValueError("固件升级申请的版本须不同于原批准版本")
        if change_type is ChangeType.PARTS_REPLACEMENT and not part_changes:
            raise ValueError("关键零件更换须说明更换内容")

    def submit_review(
        self,
        application_id: str,
        *,
        dimension: ReviewDimension,
        reviewer: str,
        passed: bool,
        on: date,
        comment: str = "",
    ) -> None:
        """提交单个维度的审查结论；四类审查可并行开展。"""
        application = self._application(application_id)
        if application.status is not ApplicationStatus.PENDING:
            raise ValueError("申请已办结，无法继续审查")
        application.reviews[dimension] = Review(
            dimension=dimension, reviewer=reviewer, passed=passed, decided_on=on, comment=comment
        )

    def approve(
        self,
        application_id: str,
        *,
        headcount_limit: int,
        review_date: date,
        on: date,
    ) -> Approval:
        """结论齐全且证据仍在有效期内才可批准，写明适用场景、人数上限和复评日期。"""
        application = self._application(application_id)
        if application.status is not ApplicationStatus.PENDING:
            raise ValueError("申请已办结")
        missing = [d.value for d in ReviewDimension if d not in application.reviews]
        if missing:
            raise ValueError(f"审查结论不齐全：{missing}")
        failed = [r.dimension.value for r in application.reviews.values() if not r.passed]
        if failed:
            raise ValueError(f"存在未通过的审查结论：{failed}")
        model = self._model(application.model_code)
        if model.status is not ModelStatus.ACTIVE:
            raise ValueError(f"型号当前不可用（{model.status.value}）")
        expired = [e.evidence_id for e in model.evidence.values() if not e.is_valid_on(on)]
        if expired:
            raise ValueError(f"证据已过有效期：{expired}")
        if not 1 <= headcount_limit <= application.scope.requested_headcount:
            raise ValueError("人数上限须介于 1 与申请上限之间")
        if review_date <= on:
            raise ValueError("复评日期须晚于批准日期")
        application.status = ApplicationStatus.APPROVED
        approval = Approval(
            approval_no=self._next_id("approval", "ZS"),
            application_id=application_id,
            scenic_area=application.scenic_area,
            model_code=application.model_code,
            software_version=application.software_version,
            scenarios=application.scope.zones,
            headcount_limit=headcount_limit,
            review_date=review_date,
            issued_on=on,
        )
        self._approvals[approval.approval_no] = approval
        return approval

    # ------------------------------------------------------------------
    # 部署
    # ------------------------------------------------------------------

    def deploy(
        self,
        approval_no: str,
        *,
        unit_serial: str,
        zone: str,
        firmware_version: str,
        on: date,
    ) -> str:
        """在批准记录下部署一台设备，受适用场景与人数上限约束。"""
        approval = self._approval(approval_no)
        if approval.status is not ApprovalStatus.ACTIVE:
            raise ValueError(f"批准记录当前不可用（{approval.status.value}）")
        if not approval.issued_on <= on <= approval.review_date:
            raise ValueError("不在批准有效期内，需重新评估")
        model = self._model(approval.model_code)
        if model.status is not ModelStatus.ACTIVE:
            raise ValueError(f"型号当前不可用（{model.status.value}）")
        if zone not in approval.scenarios:
            raise ValueError(f"部署区域超出适用范围：{zone}")
        if firmware_version != approval.software_version:
            raise ValueError("固件版本与批准记录不符，须提交新申请")
        for dep in self._deployments.values():
            if dep.unit_serial == unit_serial and dep.status is not DeploymentStatus.TERMINATED:
                raise ValueError(f"设备已存在部署记录：{unit_serial}")
        in_service = sum(
            1
            for dep in self._deployments.values()
            if dep.approval_no == approval_no and dep.status is not DeploymentStatus.TERMINATED
        )
        if in_service >= approval.headcount_limit:
            raise ValueError("已达到批准的人数上限")
        deployment_id = self._next_id("deployment", "BS")
        self._deployments[deployment_id] = Deployment(
            deployment_id=deployment_id,
            approval_no=approval_no,
            unit_serial=unit_serial,
            zone=zone,
            firmware_version=firmware_version,
            started_on=on,
        )
        return deployment_id

    # ------------------------------------------------------------------
    # 事件处置与复核恢复
    # ------------------------------------------------------------------

    def report_incident(
        self,
        *,
        kind: IncidentKind,
        severity: Severity,
        deployment_id: str,
        description: str,
        on: date,
    ) -> str:
        """事故、投诉、抽检异常按严重度触发单点暂停、同型号排查或全面撤销。"""
        deployment = self._deployment(deployment_id)
        if deployment.status is DeploymentStatus.TERMINATED:
            raise ValueError("部署已终止")
        approval = self._approval(deployment.approval_no)
        model = self._model(approval.model_code)
        incident_id = self._next_id("incident", "SJ")
        if severity is Severity.MINOR:
            deployment.status = DeploymentStatus.SUSPENDED
            affected = (deployment_id,)
        elif severity is Severity.SERIOUS:
            model.status = ModelStatus.UNDER_INVESTIGATION
            affected = self._model_deployments(model.model_code)
            for item in self._approvals.values():
                if item.model_code == model.model_code and item.status is ApprovalStatus.ACTIVE:
                    item.status = ApprovalStatus.SUSPENDED
            for dep_id in affected:
                self._deployments[dep_id].status = DeploymentStatus.SUSPENDED
        else:
            model.status = ModelStatus.REVOKED
            affected = self._model_deployments(model.model_code)
            for item in self._approvals.values():
                if item.model_code == model.model_code and item.status is not ApprovalStatus.REVOKED:
                    item.status = ApprovalStatus.REVOKED
            for dep_id in affected:
                self._deployments[dep_id].status = DeploymentStatus.TERMINATED
        self._incidents[incident_id] = Incident(
            incident_id=incident_id,
            kind=kind,
            severity=severity,
            deployment_id=deployment_id,
            model_code=model.model_code,
            reported_on=on,
            description=description,
            affected_deployments=affected,
        )
        return incident_id

    def submit_re_review(
        self,
        incident_id: str,
        *,
        reviewer: str,
        passed: bool,
        on: date,
        notes: str = "",
    ) -> None:
        """整改后的复核；恢复只能来自有记录且结论为通过的复核。"""
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise ValueError(f"事件不存在：{incident_id}")
        if incident.status is IncidentStatus.RESOLVED:
            raise ValueError("事件已复核结案")
        self._re_reviews.append(
            ReReview(incident_id=incident_id, reviewer=reviewer, passed=passed, decided_on=on, notes=notes)
        )
        if not passed:
            return
        incident.status = IncidentStatus.RESOLVED
        model = self._model(incident.model_code)
        if incident.severity is Severity.CRITICAL:
            # 证书与部署已撤销，不可恢复；型号整改复核通过后方可重新申请
            if not self._model_has_open_investigation(model.model_code):
                model.status = ModelStatus.ACTIVE
            return
        if incident.severity is Severity.SERIOUS and not self._model_has_open_investigation(
            model.model_code
        ):
            model.status = ModelStatus.ACTIVE
            for item in self._approvals.values():
                if item.model_code == model.model_code and item.status is ApprovalStatus.SUSPENDED:
                    item.status = ApprovalStatus.ACTIVE
        for dep_id in incident.affected_deployments:
            dep = self._deployments[dep_id]
            if dep.status is not DeploymentStatus.SUSPENDED:
                continue
            if self._has_open_incident(dep_id):
                continue
            approval = self._approval(dep.approval_no)
            if approval.status is ApprovalStatus.ACTIVE and model.status is ModelStatus.ACTIVE:
                dep.status = DeploymentStatus.ACTIVE

    # ------------------------------------------------------------------
    # 追溯与公众查询
    # ------------------------------------------------------------------

    def trace_deployment(self, deployment_id: str, *, on: date) -> TraceReport:
        """监管人员从一次部署追到对应证据与审查责任人。"""
        dep = self._deployment(deployment_id)
        approval = self._approval(dep.approval_no)
        application = self._application(approval.application_id)
        model = self._model(approval.model_code)
        reviews = tuple(
            ReviewTrace(
                dimension=review.dimension.value,
                reviewer=review.reviewer,
                passed=review.passed,
                decided_on=review.decided_on,
            )
            for review in sorted(application.reviews.values(), key=lambda r: r.dimension.value)
        )
        evidence = tuple(
            EvidenceTrace(
                evidence_id=item.evidence_id,
                kind=item.kind.value,
                title=item.title,
                issuer=item.issuer,
                valid_until=item.valid_until,
                still_valid=item.is_valid_on(on),
            )
            for item in model.evidence.values()
        )
        incident_ids = tuple(
            item.incident_id
            for item in self._incidents.values()
            if deployment_id in item.affected_deployments
        )
        return TraceReport(
            deployment_id=dep.deployment_id,
            unit_serial=dep.unit_serial,
            zone=dep.zone,
            firmware_version=dep.firmware_version,
            deployment_status=dep.status.value,
            approval_no=approval.approval_no,
            approval_status=approval.status.value,
            scenarios=approval.scenarios,
            headcount_limit=approval.headcount_limit,
            review_date=approval.review_date,
            application_id=application.application_id,
            change_type=application.change_type.value,
            supersedes=application.supersedes,
            reviews=reviews,
            evidence=evidence,
            incident_ids=incident_ids,
        )

    def public_model_view(self, model_code: str, *, on: date) -> PublicModelView:
        """公众查询：只显示适用范围与风险提示，不暴露商业秘密。"""
        model = self._model(model_code)
        live = [
            item
            for item in self._approvals.values()
            if item.model_code == model_code
            and item.status is ApprovalStatus.ACTIVE
            and item.review_date >= on
        ]
        scenarios = tuple(dict.fromkeys(zone for item in live for zone in item.scenarios))
        return PublicModelView(
            model_code=model.model_code,
            manufacturer=model.manufacturer,
            device_class=model.device_class,
            status=model.status.value,
            scenarios=scenarios,
            risk_notices=model.risk_notices,
            privacy_notice=self._privacy_notice(model),
            review_dates=tuple(item.review_date for item in live),
        )

    def public_scenic_view(self, scenic_area: str, *, on: date) -> tuple[PublicDeploymentView, ...]:
        """公众查询某景区当前在运行的设备。"""
        views = []
        for dep in self._deployments.values():
            if dep.status is not DeploymentStatus.ACTIVE:
                continue
            approval = self._approval(dep.approval_no)
            if approval.scenic_area != scenic_area or approval.review_date < on:
                continue
            model = self._model(approval.model_code)
            views.append(
                PublicDeploymentView(
                    scenic_area=scenic_area,
                    model_code=model.model_code,
                    zone=dep.zone,
                    risk_notices=model.risk_notices,
                    privacy_notice=self._privacy_notice(model),
                    review_date=approval.review_date,
                )
            )
        return tuple(views)

    # ------------------------------------------------------------------
    # 监管内部读取
    # ------------------------------------------------------------------

    def get_model(self, model_code: str) -> DeviceModel:
        return self._model(model_code)

    def get_application(self, application_id: str) -> TrialApplication:
        return self._application(application_id)

    def get_approval(self, approval_no: str) -> Approval:
        return self._approval(approval_no)

    def get_deployment(self, deployment_id: str) -> Deployment:
        return self._deployment(deployment_id)

    def get_incident(self, incident_id: str) -> Incident:
        return self._incident(incident_id)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _next_id(self, kind: str, prefix: str) -> str:
        self._counters[kind] += 1
        return f"{prefix}-{self._counters[kind]:04d}"

    def _model(self, model_code: str) -> DeviceModel:
        model = self._models.get(model_code)
        if model is None:
            raise ValueError(f"型号未登记：{model_code}")
        return model

    def _application(self, application_id: str) -> TrialApplication:
        application = self._applications.get(application_id)
        if application is None:
            raise ValueError(f"申请不存在：{application_id}")
        return application

    def _approval(self, approval_no: str) -> Approval:
        approval = self._approvals.get(approval_no)
        if approval is None:
            raise ValueError(f"批准记录不存在：{approval_no}")
        return approval

    def _deployment(self, deployment_id: str) -> Deployment:
        deployment = self._deployments.get(deployment_id)
        if deployment is None:
            raise ValueError(f"部署不存在：{deployment_id}")
        return deployment

    def _incident(self, incident_id: str) -> Incident:
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise ValueError(f"事件不存在：{incident_id}")
        return incident

    def _model_deployments(self, model_code: str) -> tuple[str, ...]:
        return tuple(
            dep.deployment_id
            for dep in self._deployments.values()
            if self._approval(dep.approval_no).model_code == model_code
            and dep.status is not DeploymentStatus.TERMINATED
        )

    def _model_has_open_investigation(self, model_code: str) -> bool:
        return any(
            item.status is IncidentStatus.OPEN
            and item.model_code == model_code
            and item.severity in (Severity.SERIOUS, Severity.CRITICAL)
            for item in self._incidents.values()
        )

    def _has_open_incident(self, deployment_id: str) -> bool:
        return any(
            item.status is IncidentStatus.OPEN and deployment_id in item.affected_deployments
            for item in self._incidents.values()
        )

    def _privacy_notice(self, model: DeviceModel) -> str:
        level = self._classes[model.device_class].privacy_level
        return _PRIVACY_NOTICES.get(level, _DEFAULT_PRIVACY_NOTICE)
