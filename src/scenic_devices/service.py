"""文旅智能设备试点监管服务。

围绕型号档案、试运行申请、并行审查、批准证书、部署、事故处置与复核
恢复的规则引擎。所有规则都以日期为参数，便于审计与测试。
"""

from __future__ import annotations

from datetime import date

from .registry import DeviceClass
from .supervision import (
    ApplicationStatus,
    Certificate,
    CertificateStatus,
    Deployment,
    DeploymentStatus,
    Incident,
    ModelDossier,
    ModelStatus,
    PublicModelView,
    ReReview,
    ReviewConclusion,
    ReviewDimension,
    ReviewOutcome,
    Severity,
    TrialApplication,
)

REQUIRED_DIMENSIONS = frozenset(ReviewDimension)


class RegulatoryService:
    """监管部门使用的准入与处置服务。"""

    def __init__(self, device_classes: list[DeviceClass]) -> None:
        self._device_classes = {d.code: d for d in device_classes}
        self._dossiers: dict[str, ModelDossier] = {}
        self._applications: dict[str, TrialApplication] = {}
        self._certificates: dict[str, Certificate] = {}
        self._deployments: dict[str, Deployment] = {}
        self._incidents: dict[str, Incident] = {}
        self._rereviews: list[tuple[str, ReReview]] = []

    # ---- 型号档案 -------------------------------------------------------

    def register_dossier(self, dossier: ModelDossier) -> None:
        """登记型号档案，接入现有设备类型与安全限制。"""
        if dossier.model_code in self._dossiers:
            raise ValueError("型号档案已存在")
        device_class = self._device_classes.get(dossier.device_class)
        if device_class is None:
            raise ValueError(f"未知设备类型: {dossier.device_class}")
        if not dossier.firmware_versions:
            raise ValueError("型号档案必须声明至少一个固件版本")
        if not dossier.hardware_revisions:
            raise ValueError("型号档案必须声明至少一个硬件版本")
        if "recording" in device_class.capabilities and not dossier.privacy_processing:
            raise ValueError("具备影像能力的设备必须说明隐私处理方式")
        if not dossier.evidence:
            raise ValueError("型号档案必须附带安全测试等证据")
        self._dossiers[dossier.model_code] = dossier

    def register_firmware_version(self, model_code: str, version: str) -> None:
        """厂商登记新固件版本；已发证书仍锁定旧版本，部署新固件须重新申请。"""
        dossier = self._dossier(model_code)
        if version in dossier.firmware_versions:
            raise ValueError("固件版本已登记")
        dossier.firmware_versions = (*dossier.firmware_versions, version)

    def register_hardware_revision(self, model_code: str, revision: str) -> None:
        dossier = self._dossier(model_code)
        if revision in dossier.hardware_revisions:
            raise ValueError("硬件版本已登记")
        dossier.hardware_revisions = (*dossier.hardware_revisions, revision)

    # ---- 型号选用 -------------------------------------------------------

    def is_model_selectable(self, model_code: str, today: date) -> bool:
        """景区只能选用当前有效（未排查、未撤销）的型号。"""
        dossier = self._dossiers.get(model_code)
        return dossier is not None and dossier.status is ModelStatus.ACTIVE

    def available_models(self, today: date) -> list[str]:
        return [
            code
            for code in self._dossiers
            if self.is_model_selectable(code, today)
        ]

    # ---- 试运行申请与并行审查 -------------------------------------------

    def submit_application(self, application: TrialApplication, today: date) -> None:
        dossier = self._dossier(application.model_code)
        if application.application_id in self._applications:
            raise ValueError("申请编号已存在")
        if not self.is_model_selectable(application.model_code, today):
            raise ValueError("该型号当前不可选用")
        if application.firmware_version not in dossier.firmware_versions:
            raise ValueError("固件版本未在型号档案中登记")
        if application.hardware_revision not in dossier.hardware_revisions:
            raise ValueError("硬件版本未在型号档案中登记")
        device_class = self._device_classes[dossier.device_class]
        if device_class.requires_staff_handover and application.staffing < 1:
            raise ValueError("该设备类型要求现场交接人员，人员配置不足")
        if application.max_visitors < 1:
            raise ValueError("人数上限必须为正数")
        if application.change_reason is not None:
            self._validate_change(application)
        self._applications[application.application_id] = application

    def record_review(self, application_id: str, conclusion: ReviewConclusion) -> None:
        """记录单一维度的审查结论；四个维度可并行、按任意顺序提交。"""
        application = self._application(application_id)
        if application.status is not ApplicationStatus.IN_REVIEW:
            raise ValueError("申请已办结，不能再记录审查结论")
        dossier = self._dossier(application.model_code)
        for evidence_id in conclusion.evidence_ids:
            evidence = dossier.evidence.get(evidence_id)
            if evidence is None:
                raise ValueError(f"证据不存在: {evidence_id}")
            if not evidence.is_valid_on(conclusion.decided_on):
                raise ValueError(f"证据在审查作出之日已失效: {evidence_id}")
        application.reviews[conclusion.dimension] = conclusion

    def approve(
        self,
        application_id: str,
        certificate_id: str,
        today: date,
        review_by: date,
    ) -> Certificate:
        """四个维度结论齐全、通过且证据仍在有效期内，才可发证。"""
        application = self._application(application_id)
        if application.status is not ApplicationStatus.IN_REVIEW:
            raise ValueError("申请已办结")
        missing = REQUIRED_DIMENSIONS - application.reviews.keys()
        if missing:
            names = ", ".join(sorted(d.value for d in missing))
            raise ValueError(f"审查结论不齐全，缺少: {names}")
        for conclusion in application.reviews.values():
            if conclusion.outcome is not ReviewOutcome.PASS:
                raise ValueError(f"审查未通过: {conclusion.dimension.value}")
        dossier = self._dossier(application.model_code)
        for conclusion in application.reviews.values():
            for evidence_id in conclusion.evidence_ids:
                if not dossier.evidence[evidence_id].is_valid_on(today):
                    raise ValueError(f"证据已失效，不得批准: {evidence_id}")
        if review_by <= today:
            raise ValueError("复评日期必须晚于批准日期")
        if certificate_id in self._certificates:
            raise ValueError("证书编号已存在")

        certificate = Certificate(
            certificate_id=certificate_id,
            application_id=application_id,
            model_code=application.model_code,
            firmware_version=application.firmware_version,
            hardware_revision=application.hardware_revision,
            scenic_area=application.scenic_area,
            scenarios=application.scenarios,
            max_visitors=application.max_visitors,
            issued_on=today,
            review_by=review_by,
        )
        application.status = ApplicationStatus.APPROVED
        if application.replaces_certificate is not None:
            old = self._certificate(application.replaces_certificate)
            old.status = CertificateStatus.SUPERSEDED
            for deployment in self._deployments.values():
                if (
                    deployment.certificate_id == old.certificate_id
                    and deployment.status is DeploymentStatus.ACTIVE
                ):
                    deployment.status = DeploymentStatus.TERMINATED
        self._certificates[certificate_id] = certificate
        return certificate

    def reject(self, application_id: str) -> None:
        application = self._application(application_id)
        if application.status is not ApplicationStatus.IN_REVIEW:
            raise ValueError("申请已办结")
        application.status = ApplicationStatus.REJECTED

    # ---- 部署 -----------------------------------------------------------

    def is_certificate_valid(self, certificate_id: str, today: date) -> bool:
        certificate = self._certificate(certificate_id)
        dossier = self._dossier(certificate.model_code)
        return (
            certificate.status is CertificateStatus.VALID
            and certificate.review_by >= today
            and dossier.status is ModelStatus.ACTIVE
        )

    def deploy(
        self,
        certificate_id: str,
        deployment_id: str,
        firmware_version: str,
        today: date,
    ) -> Deployment:
        """按证书部署；固件必须与证书锁定版本一致，杜绝套用旧证书。"""
        certificate = self._certificate(certificate_id)
        if deployment_id in self._deployments:
            raise ValueError("部署编号已存在")
        if not self.is_certificate_valid(certificate_id, today):
            raise ValueError("证书当前无效，不能部署")
        if firmware_version != certificate.firmware_version:
            raise ValueError("部署固件与证书锁定版本不一致，须重新申请")
        deployment = Deployment(
            deployment_id=deployment_id,
            certificate_id=certificate_id,
            model_code=certificate.model_code,
            scenic_area=certificate.scenic_area,
            firmware_version=firmware_version,
            started_on=today,
        )
        self._deployments[deployment_id] = deployment
        return deployment

    def check_scope(self, deployment_id: str, scenario: str, visitors: int) -> None:
        """部署不得超出证书限定的场景与人数上限。"""
        deployment = self._deployment(deployment_id)
        certificate = self._certificate(deployment.certificate_id)
        if scenario not in certificate.scenarios:
            raise ValueError(f"场景超出批准范围: {scenario}")
        if visitors > certificate.max_visitors:
            raise ValueError("同时服务人数超出批准上限")

    # ---- 变更：固件升级、关键零件更换、范围扩大 --------------------------

    def file_change_application(
        self,
        application: TrialApplication,
        today: date,
    ) -> None:
        """变更必须产生新申请；批准后旧证书作废，不能套用。"""
        if application.change_reason is None or application.replaces_certificate is None:
            raise ValueError("变更申请必须注明变更原因与被替代的证书")
        self.submit_application(application, today)

    def _validate_change(self, application: TrialApplication) -> None:
        if application.replaces_certificate is None:
            raise ValueError("变更申请必须指明被替代的证书")
        old = self._certificate(application.replaces_certificate)
        if old.status not in (CertificateStatus.VALID, CertificateStatus.SUSPENDED):
            raise ValueError("被替代的证书已失效")
        if old.model_code != application.model_code:
            raise ValueError("变更申请不得更换型号")
        changed = (
            application.firmware_version != old.firmware_version
            or application.hardware_revision != old.hardware_revision
            or application.scenarios != old.scenarios
            or application.max_visitors != old.max_visitors
        )
        if not changed:
            raise ValueError("未发生固件、硬件或范围变化，不构成变更申请")

    # ---- 事故处置与复核恢复 ----------------------------------------------

    def report_incident(self, incident: Incident) -> None:
        """按严重度触发单点暂停、同型号排查或全面撤销。"""
        if incident.incident_id in self._incidents:
            raise ValueError("事件编号已存在")
        dossier = self._dossier(incident.model_code)
        self._incidents[incident.incident_id] = incident
        if incident.severity is Severity.MINOR:
            if incident.deployment_id is None:
                raise ValueError("单点暂停必须指明部署")
            self._deployment(incident.deployment_id).status = DeploymentStatus.SUSPENDED
        elif incident.severity is Severity.SERIOUS:
            dossier.status = ModelStatus.UNDER_INVESTIGATION
            for certificate in self._model_certificates(incident.model_code):
                if certificate.status is CertificateStatus.VALID:
                    certificate.status = CertificateStatus.SUSPENDED
            for deployment in self._model_deployments(incident.model_code):
                if deployment.status is DeploymentStatus.ACTIVE:
                    deployment.status = DeploymentStatus.SUSPENDED
        else:
            dossier.status = ModelStatus.REVOKED
            for certificate in self._model_certificates(incident.model_code):
                if certificate.status in (
                    CertificateStatus.VALID,
                    CertificateStatus.SUSPENDED,
                ):
                    certificate.status = CertificateStatus.REVOKED
            for deployment in self._model_deployments(incident.model_code):
                if deployment.status is not DeploymentStatus.TERMINATED:
                    deployment.status = DeploymentStatus.TERMINATED

    def close_incident(self, incident_id: str, rereview: ReReview, today: date) -> None:
        """整改后的恢复只能来自有记录的复核；全面撤销不可恢复，须重新申请。"""
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise ValueError(f"未知事件: {incident_id}")
        if not rereview.reviewer or not rereview.notes:
            raise ValueError("复核必须记录责任人与结论")
        if incident.severity is Severity.CRITICAL:
            raise ValueError("已全面撤销的型号不能恢复，须重新申请准入")
        self._rereviews.append((incident_id, rereview))
        if incident.severity is Severity.MINOR:
            deployment = self._deployment(incident.deployment_id)  # type: ignore[arg-type]
            if self.is_certificate_valid(deployment.certificate_id, today):
                deployment.status = DeploymentStatus.ACTIVE
            return
        dossier = self._dossier(incident.model_code)
        dossier.status = ModelStatus.ACTIVE
        for certificate in self._model_certificates(incident.model_code):
            if certificate.status is CertificateStatus.SUSPENDED:
                certificate.status = CertificateStatus.VALID
        for deployment in self._model_deployments(incident.model_code):
            if deployment.status is DeploymentStatus.SUSPENDED and self.is_certificate_valid(
                deployment.certificate_id, today
            ):
                deployment.status = DeploymentStatus.ACTIVE

    # ---- 追溯与公众查询 ----------------------------------------------------

    def trace_deployment(self, deployment_id: str) -> dict:
        """从一次部署追到对应证据与审查责任人。"""
        deployment = self._deployment(deployment_id)
        certificate = self._certificate(deployment.certificate_id)
        application = self._application(certificate.application_id)
        dossier = self._dossier(deployment.model_code)
        return {
            "deployment": deployment,
            "certificate": certificate,
            "application": application,
            "reviews": {
                dimension.value: {
                    "reviewer": conclusion.reviewer,
                    "outcome": conclusion.outcome.value,
                    "decided_on": conclusion.decided_on,
                }
                for dimension, conclusion in application.reviews.items()
            },
            "evidence": [
                dossier.evidence[evidence_id]
                for conclusion in application.reviews.values()
                for evidence_id in conclusion.evidence_ids
            ],
        }

    def public_catalog(self, today: date) -> list[PublicModelView]:
        """公众视图：显示适用范围与风险提示，不暴露商业秘密。"""
        views = []
        for dossier in self._dossiers.values():
            valid = [
                c
                for c in self._model_certificates(dossier.model_code)
                if self.is_certificate_valid(c.certificate_id, today)
            ]
            scenarios = tuple(sorted({s for c in valid for s in c.scenarios}))
            views.append(
                PublicModelView(
                    model_code=dossier.model_code,
                    device_class=dossier.device_class,
                    manufacturer=dossier.manufacturer,
                    status=dossier.status.value,
                    scenarios=scenarios,
                    max_visitors=max((c.max_visitors for c in valid), default=None),
                    review_by=min((c.review_by for c in valid), default=None),
                    risk_notices=dossier.risk_notices,
                )
            )
        return views

    # ---- 内部工具 -----------------------------------------------------------

    def _dossier(self, model_code: str) -> ModelDossier:
        dossier = self._dossiers.get(model_code)
        if dossier is None:
            raise ValueError(f"未知型号: {model_code}")
        return dossier

    def _application(self, application_id: str) -> TrialApplication:
        application = self._applications.get(application_id)
        if application is None:
            raise ValueError(f"未知申请: {application_id}")
        return application

    def _certificate(self, certificate_id: str) -> Certificate:
        certificate = self._certificates.get(certificate_id)
        if certificate is None:
            raise ValueError(f"未知证书: {certificate_id}")
        return certificate

    def _deployment(self, deployment_id: str) -> Deployment:
        deployment = self._deployments.get(deployment_id)
        if deployment is None:
            raise ValueError(f"未知部署: {deployment_id}")
        return deployment

    def _model_certificates(self, model_code: str) -> list[Certificate]:
        return [c for c in self._certificates.values() if c.model_code == model_code]

    def _model_deployments(self, model_code: str) -> list[Deployment]:
        return [d for d in self._deployments.values() if d.model_code == model_code]
