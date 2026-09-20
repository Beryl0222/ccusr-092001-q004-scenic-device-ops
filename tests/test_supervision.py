import sys
import unittest
from dataclasses import fields
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from scenic_devices.registry import load_device_classes
from scenic_devices.supervision import (
    ApprovalStatus,
    CapabilityBoundary,
    ChangeType,
    DeploymentStatus,
    DeviceModel,
    Evidence,
    EvidenceKind,
    IncidentKind,
    MaintenancePlan,
    ModelStatus,
    PublicModelView,
    RegulatoryService,
    ReviewDimension,
    Sensor,
    Severity,
    SoftwareVersion,
    TrialScope,
)

DATA = Path(__file__).parents[1] / "data" / "devices.json"
DAY = date(2026, 9, 1)
VALID_UNTIL = date(2027, 8, 31)
REVIEW_DATE = date(2027, 8, 31)


def make_evidence(eid, kind, valid_until=VALID_UNTIL):
    return Evidence(
        evidence_id=eid,
        kind=kind,
        title=f"{kind.value}材料",
        issuer="检测机构",
        issued_on=date(2025, 9, 1),
        valid_until=valid_until,
    )


def make_model(
    model_code="GB-100",
    device_class="guide-bot",
    functions=("navigation", "explanation"),
    privacy_processing="影像本地脱敏后上传",
    handover=False,
    evidence_valid_until=VALID_UNTIL,
):
    return DeviceModel(
        model_code=model_code,
        manufacturer="伴游科技",
        device_class=device_class,
        capability_boundary=CapabilityBoundary(functions=functions),
        privacy_processing=privacy_processing,
        maintenance_plan=MaintenancePlan(
            summary="每日巡检", interval_days=1, covers_staff_handover=handover
        ),
        sensors=(Sensor("激光雷达", "避障"),),
        risk_notices=("人流密集区请减速慢行",),
        software_versions={"1.0.0": SoftwareVersion("1.0.0", released_on=date(2026, 1, 1))},
        evidence={
            "E-ST": make_evidence("E-ST", EvidenceKind.SAFETY_TEST, evidence_valid_until),
            "E-PP": make_evidence("E-PP", EvidenceKind.PRIVACY_PROCESSING, evidence_valid_until),
            "E-MP": make_evidence("E-MP", EvidenceKind.MAINTENANCE_PLAN, evidence_valid_until),
        },
    )


def make_scope(zones=("东门环线",), requested_headcount=10, certified_operators=2):
    return TrialScope(
        zones=zones,
        terrain="平缓步道",
        expected_daily_visitors=5000,
        on_site_staff=6,
        certified_operators=certified_operators,
        requested_headcount=requested_headcount,
    )


class RegulatoryServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = RegulatoryService(load_device_classes(DATA))
        self.service.register_model(make_model())

    def apply(self, **kw):
        params = dict(
            scenic_area="云山景区",
            model_code="GB-100",
            software_version="1.0.0",
            scope=make_scope(),
            on=DAY,
        )
        params.update(kw)
        return self.service.submit_application(**params)

    def review_all(self, application_id, on=DAY):
        for dimension in ReviewDimension:
            self.service.submit_review(
                application_id,
                dimension=dimension,
                reviewer=f"{dimension.value}审查员",
                passed=True,
                on=on,
            )

    def approve_new(self, headcount_limit=5, review_date=REVIEW_DATE, **kw):
        application_id = self.apply(**kw)
        self.review_all(application_id)
        return self.service.approve(
            application_id, headcount_limit=headcount_limit, review_date=review_date, on=DAY
        )

    def deploy_one(self, approval, serial="UNIT-001", zone="东门环线", firmware="1.0.0"):
        return self.service.deploy(
            approval.approval_no,
            unit_serial=serial,
            zone=zone,
            firmware_version=firmware,
            on=DAY,
        )

    # -- 型号档案接入现有设备类型与安全限制 --------------------------------

    def test_register_model_rejects_unknown_device_class(self):
        model = make_model(model_code="XX-1", device_class="unknown-class")
        with self.assertRaisesRegex(ValueError, "设备类型未登记"):
            self.service.register_model(model)

    def test_register_model_rejects_capability_beyond_class(self):
        model = make_model(model_code="XX-2", functions=("navigation", "flight"))
        with self.assertRaisesRegex(ValueError, "能力边界超出设备类型能力"):
            self.service.register_model(model)

    def test_register_model_recording_requires_privacy_processing(self):
        model = make_model(model_code="XX-3", functions=("recording",), privacy_processing="")
        with self.assertRaisesRegex(ValueError, "隐私处理"):
            self.service.register_model(model)

    def test_register_model_requires_handover_maintenance(self):
        model = make_model(
            model_code="AF-1",
            device_class="assist-frame",
            functions=("uphill-assist",),
            handover=False,
        )
        with self.assertRaisesRegex(ValueError, "人员交接"):
            self.service.register_model(model)

    def test_register_model_requires_complete_evidence(self):
        model = make_model(model_code="XX-4")
        del model.evidence["E-ST"]
        with self.assertRaisesRegex(ValueError, "缺少证据"):
            self.service.register_model(model)

    # -- 并行审查与批准 ----------------------------------------------------

    def test_approval_waits_for_all_four_reviews(self):
        application_id = self.apply()
        for dimension in (
            ReviewDimension.TECHNICAL,
            ReviewDimension.ACCESSIBILITY,
            ReviewDimension.SAFETY,
        ):
            self.service.submit_review(
                application_id, dimension=dimension, reviewer="审查员", passed=True, on=DAY
            )
        with self.assertRaisesRegex(ValueError, "审查结论不齐全"):
            self.service.approve(application_id, headcount_limit=5, review_date=REVIEW_DATE, on=DAY)
        self.service.submit_review(
            application_id,
            dimension=ReviewDimension.DATA_PROTECTION,
            reviewer="数据保护审查员",
            passed=True,
            on=DAY,
        )
        approval = self.service.approve(
            application_id, headcount_limit=5, review_date=REVIEW_DATE, on=DAY
        )
        self.assertEqual(approval.scenarios, ("东门环线",))

    def test_approval_blocked_by_failed_review_until_replaced(self):
        application_id = self.apply()
        self.review_all(application_id)
        self.service.submit_review(
            application_id,
            dimension=ReviewDimension.SAFETY,
            reviewer="安全审查员",
            passed=False,
            on=DAY,
            comment="制动测试未达标",
        )
        with self.assertRaisesRegex(ValueError, "未通过"):
            self.service.approve(application_id, headcount_limit=5, review_date=REVIEW_DATE, on=DAY)
        self.service.submit_review(
            application_id,
            dimension=ReviewDimension.SAFETY,
            reviewer="安全审查员",
            passed=True,
            on=DAY,
            comment="整改后复测通过",
        )
        approval = self.service.approve(
            application_id, headcount_limit=5, review_date=REVIEW_DATE, on=DAY
        )
        self.assertEqual(approval.status, ApprovalStatus.ACTIVE)

    def test_approval_requires_evidence_in_validity(self):
        self.service.register_model(
            make_model(model_code="GB-EXP", evidence_valid_until=date(2026, 6, 30))
        )
        application_id = self.apply(model_code="GB-EXP")
        self.review_all(application_id)
        with self.assertRaisesRegex(ValueError, "证据已过有效期"):
            self.service.approve(application_id, headcount_limit=5, review_date=REVIEW_DATE, on=DAY)
        self.service.add_evidence(
            "GB-EXP", make_evidence("E-ST", EvidenceKind.SAFETY_TEST, VALID_UNTIL)
        )
        self.service.add_evidence(
            "GB-EXP", make_evidence("E-PP", EvidenceKind.PRIVACY_PROCESSING, VALID_UNTIL)
        )
        self.service.add_evidence(
            "GB-EXP", make_evidence("E-MP", EvidenceKind.MAINTENANCE_PLAN, VALID_UNTIL)
        )
        approval = self.service.approve(
            application_id, headcount_limit=5, review_date=REVIEW_DATE, on=DAY
        )
        self.assertEqual(approval.model_code, "GB-EXP")

    def test_approval_record_carries_scope_headcount_and_review_date(self):
        approval = self.approve_new(headcount_limit=8)
        self.assertEqual(approval.scenarios, ("东门环线",))
        self.assertEqual(approval.headcount_limit, 8)
        self.assertEqual(approval.review_date, REVIEW_DATE)

    def test_headcount_limit_cannot_exceed_request(self):
        application_id = self.apply()
        self.review_all(application_id)
        with self.assertRaisesRegex(ValueError, "人数上限"):
            self.service.approve(
                application_id, headcount_limit=11, review_date=REVIEW_DATE, on=DAY
            )

    # -- 部署约束 ----------------------------------------------------------

    def test_deploy_enforces_zone_firmware_serial_and_headcount(self):
        approval = self.approve_new(headcount_limit=2)
        self.deploy_one(approval, serial="UNIT-1")
        self.deploy_one(approval, serial="UNIT-2")
        with self.assertRaisesRegex(ValueError, "人数上限"):
            self.deploy_one(approval, serial="UNIT-3")
        with self.assertRaisesRegex(ValueError, "超出适用范围"):
            self.deploy_one(approval, serial="UNIT-4", zone="西区")
        with self.assertRaisesRegex(ValueError, "固件版本与批准记录不符"):
            self.deploy_one(approval, serial="UNIT-4", firmware="9.9.9")
        with self.assertRaisesRegex(ValueError, "已存在部署记录"):
            self.deploy_one(approval, serial="UNIT-1")

    def test_deploy_rejected_after_review_date(self):
        approval = self.approve_new(review_date=date(2026, 12, 31))
        with self.assertRaisesRegex(ValueError, "重新评估"):
            self.service.deploy(
                approval.approval_no,
                unit_serial="UNIT-1",
                zone="东门环线",
                firmware_version="1.0.0",
                on=date(2027, 1, 1),
            )

    def test_scenic_area_can_only_select_valid_models(self):
        approval = self.approve_new()
        deployment_id = self.deploy_one(approval)
        self.service.report_incident(
            kind=IncidentKind.INSPECTION,
            severity=Severity.SERIOUS,
            deployment_id=deployment_id,
            description="抽检发现制动隐患",
            on=DAY,
        )
        self.assertNotIn("GB-100", self.service.valid_models())
        with self.assertRaisesRegex(ValueError, "不可选用"):
            self.apply()

    # -- 变更必须产生新申请 --------------------------------------------------

    def test_firmware_upgrade_requires_new_application(self):
        old = self.approve_new()
        self.deploy_one(old, serial="UNIT-A")
        self.service.add_software_version(
            "GB-100", SoftwareVersion("1.1.0", released_on=date(2026, 8, 1))
        )
        with self.assertRaisesRegex(ValueError, "固件版本与批准记录不符"):
            self.deploy_one(old, serial="UNIT-B", firmware="1.1.0")
        with self.assertRaisesRegex(ValueError, "须不同于原批准版本"):
            self.apply(
                change_type=ChangeType.FIRMWARE_UPGRADE,
                supersedes=old.approval_no,
                software_version="1.0.0",
            )
        new = self.approve_new(
            change_type=ChangeType.FIRMWARE_UPGRADE,
            supersedes=old.approval_no,
            software_version="1.1.0",
        )
        deployment_id = self.deploy_one(new, serial="UNIT-B", firmware="1.1.0")
        self.assertEqual(
            self.service.get_deployment(deployment_id).status, DeploymentStatus.ACTIVE
        )

    def test_change_application_requires_valid_base(self):
        self.service.add_software_version(
            "GB-100", SoftwareVersion("1.1.0", released_on=date(2026, 8, 1))
        )
        with self.assertRaisesRegex(ValueError, "被替代的批准记录"):
            self.apply(change_type=ChangeType.FIRMWARE_UPGRADE, software_version="1.1.0")
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.apply(
                change_type=ChangeType.SCOPE_EXPANSION,
                supersedes="ZS-9999",
                scope=make_scope(zones=("东门环线", "西区")),
            )
        approval = self.approve_new()
        with self.assertRaisesRegex(ValueError, "更换内容"):
            self.apply(
                change_type=ChangeType.PARTS_REPLACEMENT, supersedes=approval.approval_no
            )
        application_id = self.apply(
            change_type=ChangeType.PARTS_REPLACEMENT,
            supersedes=approval.approval_no,
            part_changes=("驱动轮总成",),
        )
        self.assertEqual(
            self.service.get_application(application_id).change_type,
            ChangeType.PARTS_REPLACEMENT,
        )

    def test_scope_expansion_via_new_application(self):
        old = self.approve_new()
        with self.assertRaisesRegex(ValueError, "超出适用范围"):
            self.deploy_one(old, serial="UNIT-1", zone="西区")
        new = self.approve_new(
            change_type=ChangeType.SCOPE_EXPANSION,
            supersedes=old.approval_no,
            scope=make_scope(zones=("东门环线", "西区")),
        )
        deployment_id = self.deploy_one(new, serial="UNIT-1", zone="西区")
        self.assertEqual(self.service.get_deployment(deployment_id).zone, "西区")

    # -- 事件处置与复核恢复 --------------------------------------------------

    def test_minor_incident_suspends_single_deployment(self):
        approval = self.approve_new()
        first = self.deploy_one(approval, serial="UNIT-1")
        second = self.deploy_one(approval, serial="UNIT-2")
        incident_id = self.service.report_incident(
            kind=IncidentKind.COMPLAINT,
            severity=Severity.MINOR,
            deployment_id=first,
            description="游客投诉急停",
            on=DAY,
        )
        incident = self.service.get_incident(incident_id)
        self.assertEqual(incident.action, "单点暂停")
        self.assertEqual(
            self.service.get_deployment(first).status, DeploymentStatus.SUSPENDED
        )
        self.assertEqual(self.service.get_deployment(second).status, DeploymentStatus.ACTIVE)

    def test_serious_incident_triggers_model_wide_investigation(self):
        self.service.register_model(
            make_model(
                model_code="AF-200",
                device_class="assist-frame",
                functions=("uphill-assist",),
                handover=True,
            )
        )
        approval = self.approve_new()
        first = self.deploy_one(approval, serial="UNIT-1")
        second = self.deploy_one(approval, serial="UNIT-2")
        other = self.approve_new(model_code="AF-200")
        other_dep = self.deploy_one(other, serial="AF-1")
        incident_id = self.service.report_incident(
            kind=IncidentKind.INSPECTION,
            severity=Severity.SERIOUS,
            deployment_id=first,
            description="抽检发现制动隐患",
            on=DAY,
        )
        self.assertEqual(self.service.get_incident(incident_id).action, "同型号排查")
        self.assertEqual(
            self.service.get_model("GB-100").status, ModelStatus.UNDER_INVESTIGATION
        )
        self.assertEqual(
            self.service.get_deployment(first).status, DeploymentStatus.SUSPENDED
        )
        self.assertEqual(
            self.service.get_deployment(second).status, DeploymentStatus.SUSPENDED
        )
        self.assertEqual(self.service.get_approval(approval.approval_no).status, ApprovalStatus.SUSPENDED)
        self.assertEqual(self.service.get_deployment(other_dep).status, DeploymentStatus.ACTIVE)
        self.assertEqual(self.service.valid_models(), ("AF-200",))
        with self.assertRaisesRegex(ValueError, "不可选用"):
            self.apply()
        self.apply(model_code="AF-200")

    def test_serious_investigation_recovers_after_re_review(self):
        approval = self.approve_new()
        deployment_id = self.deploy_one(approval)
        incident_id = self.service.report_incident(
            kind=IncidentKind.ACCIDENT,
            severity=Severity.SERIOUS,
            deployment_id=deployment_id,
            description="碰撞游客",
            on=DAY,
        )
        self.service.submit_re_review(
            incident_id, reviewer="复核员", passed=True, on=DAY, notes="整改到位"
        )
        self.assertEqual(self.service.get_model("GB-100").status, ModelStatus.ACTIVE)
        self.assertEqual(self.service.get_approval(approval.approval_no).status, ApprovalStatus.ACTIVE)
        self.assertEqual(
            self.service.get_deployment(deployment_id).status, DeploymentStatus.ACTIVE
        )

    def test_critical_incident_revokes_everything(self):
        approval = self.approve_new()
        first = self.deploy_one(approval, serial="UNIT-1")
        second = self.deploy_one(approval, serial="UNIT-2")
        incident_id = self.service.report_incident(
            kind=IncidentKind.ACCIDENT,
            severity=Severity.CRITICAL,
            deployment_id=first,
            description="失控冲撞致伤",
            on=DAY,
        )
        self.assertEqual(self.service.get_incident(incident_id).action, "全面撤销")
        self.assertEqual(self.service.get_model("GB-100").status, ModelStatus.REVOKED)
        self.assertEqual(self.service.get_approval(approval.approval_no).status, ApprovalStatus.REVOKED)
        for dep in (first, second):
            self.assertEqual(
                self.service.get_deployment(dep).status, DeploymentStatus.TERMINATED
            )

    def test_recovery_only_from_recorded_re_review(self):
        approval = self.approve_new()
        deployment_id = self.deploy_one(approval)
        incident_id = self.service.report_incident(
            kind=IncidentKind.COMPLAINT,
            severity=Severity.MINOR,
            deployment_id=deployment_id,
            description="语音导览误播",
            on=DAY,
        )
        self.assertEqual(
            self.service.get_deployment(deployment_id).status, DeploymentStatus.SUSPENDED
        )
        self.service.submit_re_review(
            incident_id, reviewer="复核员", passed=False, on=DAY, notes="整改不到位"
        )
        self.assertEqual(
            self.service.get_deployment(deployment_id).status, DeploymentStatus.SUSPENDED
        )
        self.service.submit_re_review(
            incident_id, reviewer="复核员", passed=True, on=DAY, notes="复测通过"
        )
        self.assertEqual(
            self.service.get_deployment(deployment_id).status, DeploymentStatus.ACTIVE
        )
        with self.assertRaisesRegex(ValueError, "已复核结案"):
            self.service.submit_re_review(incident_id, reviewer="复核员", passed=True, on=DAY)

    def test_critical_recovery_does_not_restore_certificates(self):
        old = self.approve_new()
        deployment_id = self.deploy_one(old)
        incident_id = self.service.report_incident(
            kind=IncidentKind.ACCIDENT,
            severity=Severity.CRITICAL,
            deployment_id=deployment_id,
            description="失控冲撞致伤",
            on=DAY,
        )
        self.service.submit_re_review(incident_id, reviewer="复核员", passed=True, on=DAY)
        self.assertEqual(self.service.get_model("GB-100").status, ModelStatus.ACTIVE)
        self.assertEqual(self.service.get_approval(old.approval_no).status, ApprovalStatus.REVOKED)
        self.assertEqual(
            self.service.get_deployment(deployment_id).status, DeploymentStatus.TERMINATED
        )
        with self.assertRaisesRegex(ValueError, "已撤销"):
            self.deploy_one(old, serial="UNIT-9")
        with self.assertRaisesRegex(ValueError, "不能套用"):
            self.apply(change_type=ChangeType.SCOPE_EXPANSION, supersedes=old.approval_no)
        new = self.approve_new()
        self.deploy_one(new, serial="UNIT-9")

    # -- 追溯与公众查询 ----------------------------------------------------

    def test_trace_deployment_reaches_evidence_and_reviewers(self):
        approval = self.approve_new()
        deployment_id = self.deploy_one(approval)
        incident_id = self.service.report_incident(
            kind=IncidentKind.COMPLAINT,
            severity=Severity.MINOR,
            deployment_id=deployment_id,
            description="语音导览误播",
            on=DAY,
        )
        trace = self.service.trace_deployment(deployment_id, on=DAY)
        self.assertEqual(trace.approval_no, approval.approval_no)
        self.assertEqual(trace.change_type, "首次申请")
        reviewers = {review.dimension: review.reviewer for review in trace.reviews}
        self.assertEqual(reviewers["安全"], "安全审查员")
        self.assertEqual(reviewers["数据保护"], "数据保护审查员")
        self.assertEqual({item.evidence_id for item in trace.evidence}, {"E-ST", "E-PP", "E-MP"})
        self.assertTrue(all(item.still_valid for item in trace.evidence))
        self.assertEqual(trace.incident_ids, (incident_id,))

    def test_public_view_shows_scope_and_risks_without_trade_secrets(self):
        approval = self.approve_new()
        self.deploy_one(approval)
        view = self.service.public_model_view("GB-100", on=DAY)
        self.assertEqual(view.scenarios, ("东门环线",))
        self.assertIn("减速慢行", view.risk_notices[0])
        self.assertIn("游客同意", view.privacy_notice)
        self.assertEqual(view.review_dates, (REVIEW_DATE,))
        self.assertEqual(
            {item.name for item in fields(PublicModelView)},
            {
                "model_code",
                "manufacturer",
                "device_class",
                "status",
                "scenarios",
                "risk_notices",
                "privacy_notice",
                "review_dates",
            },
        )
        text = repr(view)
        for secret in ("安全审查员", "E-ST", "每日巡检", "激光雷达", "脱敏"):
            self.assertNotIn(secret, text)

    def test_public_scenic_view_only_lists_running_deployments(self):
        approval = self.approve_new()
        deployment_id = self.deploy_one(approval)
        views = self.service.public_scenic_view("云山景区", on=DAY)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].zone, "东门环线")
        self.assertIn("减速慢行", views[0].risk_notices[0])
        self.service.report_incident(
            kind=IncidentKind.COMPLAINT,
            severity=Severity.MINOR,
            deployment_id=deployment_id,
            description="语音导览误播",
            on=DAY,
        )
        self.assertEqual(self.service.public_scenic_view("云山景区", on=DAY), ())


if __name__ == "__main__":
    unittest.main()
