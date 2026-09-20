import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from scenic_devices.registry import DeviceClass
from scenic_devices.service import RegulatoryService
from scenic_devices.supervision import (
    ApplicationStatus,
    CertificateStatus,
    ChangeReason,
    DeploymentStatus,
    Evidence,
    Incident,
    IncidentKind,
    ModelDossier,
    ModelStatus,
    ReReview,
    ReviewConclusion,
    ReviewDimension,
    ReviewOutcome,
    Severity,
    TrialApplication,
)

DAY = timedelta(days=1)
T0 = date(2026, 3, 1)

DEVICE_CLASSES = [
    DeviceClass("guide-bot", ("navigation", "explanation", "recording"), "visitor-consent", False),
    DeviceClass("assist-frame", ("uphill-assist", "downhill-buffer"), "minimal", True),
]


def make_evidence(evidence_id: str, valid_until: date, kind: str = "safety-test") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        summary=f"{kind} 报告",
        issued_on=T0 - 30 * DAY,
        valid_until=valid_until,
    )


def make_dossier(model_code: str = "GB-100", device_class: str = "guide-bot") -> ModelDossier:
    evidence = {
        "EV-SAFE": make_evidence("EV-SAFE", T0 + 300 * DAY),
        "EV-PRIV": make_evidence("EV-PRIV", T0 + 300 * DAY, "privacy-assessment"),
    }
    return ModelDossier(
        model_code=model_code,
        manufacturer="山行机器人",
        device_class=device_class,
        capability_boundary=("平路导览", "语音讲解"),
        firmware_versions=("1.0.0",),
        hardware_revisions=("hw-a",),
        sensors=("lidar", "depth-camera"),
        privacy_processing="人脸本地模糊化后脱敏存储",
        maintenance_plan="每月巡检，关键零件按台账更换",
        risk_notices=("雨雪天气暂停户外导览", "请勿在陡坡使用跟随模式"),
        evidence=evidence,
    )


def make_application(
    application_id: str = "APP-1",
    model_code: str = "GB-100",
    firmware: str = "1.0.0",
    hardware: str = "hw-a",
    staffing: int = 2,
    **overrides,
) -> TrialApplication:
    params = dict(
        application_id=application_id,
        model_code=model_code,
        firmware_version=firmware,
        hardware_revision=hardware,
        scenic_area="云溪景区",
        terrain="山地步道，最大坡度 15°",
        visitor_flow=800,
        staffing=staffing,
        scenarios=("日间导览",),
        max_visitors=30,
    )
    params.update(overrides)
    return TrialApplication(**params)


def pass_review(dimension: ReviewDimension, decided_on: date = T0) -> ReviewConclusion:
    return ReviewConclusion(
        dimension=dimension,
        outcome=ReviewOutcome.PASS,
        reviewer=f"{dimension.value}-审查员",
        decided_on=decided_on,
        evidence_ids=("EV-SAFE", "EV-PRIV"),
    )


def approved_service() -> tuple[RegulatoryService, TrialApplication]:
    service = RegulatoryService(DEVICE_CLASSES)
    service.register_dossier(make_dossier())
    application = make_application()
    service.submit_application(application, T0)
    for dimension in ReviewDimension:
        service.record_review("APP-1", pass_review(dimension))
    service.approve("APP-1", "CERT-1", T0 + 10 * DAY, T0 + 180 * DAY)
    return service, application


class DossierRegistrationTest(unittest.TestCase):
    def test_unknown_device_class_rejected(self) -> None:
        service = RegulatoryService(DEVICE_CLASSES)
        with self.assertRaises(ValueError):
            service.register_dossier(make_dossier(device_class="hover-pod"))

    def test_recording_device_must_describe_privacy_processing(self) -> None:
        service = RegulatoryService(DEVICE_CLASSES)
        dossier = make_dossier()
        dossier.privacy_processing = ""
        with self.assertRaises(ValueError):
            service.register_dossier(dossier)

    def test_staffed_device_requires_staffing_in_application(self) -> None:
        service = RegulatoryService(DEVICE_CLASSES)
        service.register_dossier(
            make_dossier("AF-1", device_class="assist-frame")
        )
        with self.assertRaises(ValueError):
            service.submit_application(
                make_application("APP-X", model_code="AF-1", staffing=0), T0
            )


class ReviewGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RegulatoryService(DEVICE_CLASSES)
        self.service.register_dossier(make_dossier())
        self.service.submit_application(make_application(), T0)

    def test_reviews_may_arrive_in_any_order(self) -> None:
        for dimension in (
            ReviewDimension.DATA_PROTECTION,
            ReviewDimension.SAFETY,
            ReviewDimension.ACCESSIBILITY,
            ReviewDimension.TECHNICAL,
        ):
            self.service.record_review("APP-1", pass_review(dimension))
        certificate = self.service.approve("APP-1", "CERT-1", T0 + DAY, T0 + 90 * DAY)
        self.assertEqual(certificate.scenarios, ("日间导览",))
        self.assertEqual(certificate.max_visitors, 30)
        self.assertEqual(certificate.review_by, T0 + 90 * DAY)

    def test_approval_blocked_until_all_dimensions_concluded(self) -> None:
        self.service.record_review("APP-1", pass_review(ReviewDimension.SAFETY))
        with self.assertRaisesRegex(ValueError, "不齐全"):
            self.service.approve("APP-1", "CERT-1", T0 + DAY, T0 + 90 * DAY)

    def test_failed_review_blocks_approval(self) -> None:
        for dimension in ReviewDimension:
            conclusion = pass_review(dimension)
            if dimension is ReviewDimension.ACCESSIBILITY:
                conclusion = ReviewConclusion(
                    dimension=dimension,
                    outcome=ReviewOutcome.FAIL,
                    reviewer="无障碍审查员",
                    decided_on=T0,
                    evidence_ids=("EV-SAFE",),
                )
            self.service.record_review("APP-1", conclusion)
        with self.assertRaisesRegex(ValueError, "未通过"):
            self.service.approve("APP-1", "CERT-1", T0 + DAY, T0 + 90 * DAY)

    def test_expired_evidence_blocks_review_and_approval(self) -> None:
        stale = ReviewConclusion(
            dimension=ReviewDimension.SAFETY,
            outcome=ReviewOutcome.PASS,
            reviewer="安全审查员",
            decided_on=T0 + 400 * DAY,
            evidence_ids=("EV-SAFE",),
        )
        with self.assertRaisesRegex(ValueError, "已失效"):
            self.service.record_review("APP-1", stale)

        for dimension in ReviewDimension:
            self.service.record_review("APP-1", pass_review(dimension))
        with self.assertRaisesRegex(ValueError, "已失效"):
            self.service.approve("APP-1", "CERT-1", T0 + 400 * DAY, T0 + 500 * DAY)


class DeploymentAndTraceTest(unittest.TestCase):
    def test_deploy_and_trace_back_to_evidence_and_reviewers(self) -> None:
        service, _ = approved_service()
        service.deploy("CERT-1", "DEP-1", "1.0.0", T0 + 20 * DAY)
        trace = service.trace_deployment("DEP-1")
        self.assertEqual(trace["certificate"].certificate_id, "CERT-1")
        self.assertEqual(trace["application"].application_id, "APP-1")
        self.assertEqual(len(trace["reviews"]), 4)
        self.assertEqual(
            trace["reviews"]["safety"]["reviewer"], "safety-审查员"
        )
        self.assertEqual(
            {e.evidence_id for e in trace["evidence"]}, {"EV-SAFE", "EV-PRIV"}
        )

    def test_deploy_rejects_expired_certificate_and_firmware_mismatch(self) -> None:
        service, _ = approved_service()
        with self.assertRaisesRegex(ValueError, "当前无效"):
            service.deploy("CERT-1", "DEP-1", "1.0.0", T0 + 200 * DAY)
        with self.assertRaisesRegex(ValueError, "固件"):
            service.deploy("CERT-1", "DEP-1", "1.1.0", T0 + 20 * DAY)


class ChangeManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service, _ = approved_service()
        self.service.deploy("CERT-1", "DEP-1", "1.0.0", T0 + 20 * DAY)

    def test_firmware_upgrade_requires_new_application(self) -> None:
        self.service.register_firmware_version("GB-100", "1.1.0")
        change = make_application(
            "APP-2",
            firmware="1.1.0",
            change_reason=ChangeReason.FIRMWARE_UPGRADE,
            replaces_certificate="CERT-1",
        )
        self.service.submit_application(change, T0 + 30 * DAY)
        for dimension in ReviewDimension:
            self.service.record_review("APP-2", pass_review(dimension, T0 + 30 * DAY))
        certificate = self.service.approve(
            "APP-2", "CERT-2", T0 + 40 * DAY, T0 + 200 * DAY
        )
        self.assertEqual(certificate.firmware_version, "1.1.0")
        old = self.service.trace_deployment("DEP-1")["certificate"]
        self.assertIs(old.status, CertificateStatus.SUPERSEDED)
        deployment = self.service.trace_deployment("DEP-1")["deployment"]
        self.assertIs(deployment.status, DeploymentStatus.TERMINATED)
        self.service.deploy("CERT-2", "DEP-2", "1.1.0", T0 + 50 * DAY)

    def test_old_certificate_cannot_cover_new_firmware(self) -> None:
        self.service.register_firmware_version("GB-100", "1.1.0")
        with self.assertRaisesRegex(ValueError, "固件"):
            self.service.deploy("CERT-1", "DEP-2", "1.1.0", T0 + 30 * DAY)

    def test_change_application_must_reference_certificate(self) -> None:
        change = make_application(
            "APP-2",
            firmware="1.0.0",
            change_reason=ChangeReason.SCOPE_EXPANSION,
            scenarios=("日间导览", "夜间导览"),
        )
        with self.assertRaisesRegex(ValueError, "被替代的证书"):
            self.service.submit_application(change, T0 + 30 * DAY)

    def test_part_replacement_requires_registered_hardware(self) -> None:
        change = make_application(
            "APP-2",
            hardware="hw-b",
            change_reason=ChangeReason.PART_REPLACEMENT,
            replaces_certificate="CERT-1",
        )
        with self.assertRaisesRegex(ValueError, "硬件版本"):
            self.service.submit_application(change, T0 + 30 * DAY)
        self.service.register_hardware_revision("GB-100", "hw-b")
        self.service.submit_application(change, T0 + 30 * DAY)


class IncidentHandlingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service, _ = approved_service()
        self.service.deploy("CERT-1", "DEP-1", "1.0.0", T0 + 20 * DAY)
        self.service.deploy("CERT-1", "DEP-2", "1.0.0", T0 + 21 * DAY)

    def incident(self, severity: Severity, incident_id: str = "INC-1") -> Incident:
        return Incident(
            incident_id=incident_id,
            kind=IncidentKind.ACCIDENT,
            severity=severity,
            model_code="GB-100",
            occurred_on=T0 + 30 * DAY,
            detail="伴游机器人与游客发生碰撞",
            deployment_id="DEP-1" if severity is Severity.MINOR else None,
        )

    def test_minor_incident_suspends_single_deployment(self) -> None:
        self.service.report_incident(self.incident(Severity.MINOR))
        deployments = self.service._deployments
        self.assertIs(deployments["DEP-1"].status, DeploymentStatus.SUSPENDED)
        self.assertIs(deployments["DEP-2"].status, DeploymentStatus.ACTIVE)

    def test_serious_incident_suspends_whole_model(self) -> None:
        self.service.report_incident(self.incident(Severity.SERIOUS))
        self.assertFalse(self.service.is_model_selectable("GB-100", T0 + 31 * DAY))
        for deployment in self.service._deployments.values():
            self.assertIs(deployment.status, DeploymentStatus.SUSPENDED)
        with self.assertRaisesRegex(ValueError, "不可选用"):
            self.service.submit_application(make_application("APP-9"), T0 + 31 * DAY)

    def test_critical_incident_revokes_model_and_certificates(self) -> None:
        self.service.report_incident(self.incident(Severity.CRITICAL))
        self.assertEqual(self.service.available_models(T0 + 31 * DAY), [])
        certificate = self.service._certificates["CERT-1"]
        self.assertIs(certificate.status, CertificateStatus.REVOKED)
        for deployment in self.service._deployments.values():
            self.assertIs(deployment.status, DeploymentStatus.TERMINATED)

    def test_recovery_only_via_recorded_rereview(self) -> None:
        self.service.report_incident(self.incident(Severity.SERIOUS))
        with self.assertRaisesRegex(ValueError, "复核"):
            self.service.close_incident(
                "INC-1", ReReview(reviewer="", decided_on=T0 + 60 * DAY, notes=""), T0 + 60 * DAY
            )
        self.service.close_incident(
            "INC-1",
            ReReview(reviewer="复核员甲", decided_on=T0 + 60 * DAY, notes="整改完成，恢复试运行"),
            T0 + 60 * DAY,
        )
        self.assertTrue(self.service.is_model_selectable("GB-100", T0 + 60 * DAY))
        for deployment in self.service._deployments.values():
            self.assertIs(deployment.status, DeploymentStatus.ACTIVE)

    def test_critical_revocation_cannot_be_restored(self) -> None:
        self.service.report_incident(self.incident(Severity.CRITICAL))
        with self.assertRaisesRegex(ValueError, "重新申请"):
            self.service.close_incident(
                "INC-1",
                ReReview(reviewer="复核员甲", decided_on=T0 + 60 * DAY, notes="整改完成"),
                T0 + 60 * DAY,
            )

    def test_unknown_incident_cannot_be_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知事件"):
            self.service.close_incident(
                "INC-X",
                ReReview(reviewer="复核员甲", decided_on=T0, notes="记录"),
                T0,
            )


class PublicViewTest(unittest.TestCase):
    def test_public_view_shows_scope_and_risks_without_trade_secrets(self) -> None:
        service, _ = approved_service()
        (view,) = service.public_catalog(T0 + 20 * DAY)
        self.assertEqual(view.model_code, "GB-100")
        self.assertEqual(view.scenarios, ("日间导览",))
        self.assertEqual(view.max_visitors, 30)
        self.assertIn("雨雪天气暂停户外导览", view.risk_notices)
        self.assertEqual(view.status, "active")
        for secret in ("sensors", "maintenance_plan", "privacy_processing", "evidence"):
            self.assertFalse(hasattr(view, secret), secret)

    def test_public_view_marks_revoked_model(self) -> None:
        service, _ = approved_service()
        service.report_incident(
            Incident(
                incident_id="INC-1",
                kind=IncidentKind.SPOT_CHECK,
                severity=Severity.CRITICAL,
                model_code="GB-100",
                occurred_on=T0 + 30 * DAY,
                detail="抽检发现制动系统不合格",
            )
        )
        (view,) = service.public_catalog(T0 + 31 * DAY)
        self.assertEqual(view.status, "revoked")
        self.assertEqual(view.scenarios, ())


if __name__ == "__main__":
    unittest.main()
