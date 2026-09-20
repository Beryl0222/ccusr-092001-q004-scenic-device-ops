# 景区智能设备运营资料

景区正在试点伴游机器人、助行外骨骼和自助影像设备，本项目记录设备能力、服务区域、隐私等级和安全限制，并提供面向文旅智能设备试点的监管服务，避免准入证书与真实部署脱节。

Python 代码位于 `src/scenic_devices`，样例清单位于 `data/devices.json`。执行 `python -m unittest discover -s tests` 可验证设备资料与监管流程。

## 试点监管服务（scenic_devices.supervision）

- **型号档案**：厂商按型号维护能力边界、软件版本、传感器、隐私处理、安全测试和维护方案；登记时接入 `data/devices.json` 的现有设备类型与安全限制（能力边界不得超出类型能力，影像能力必须说明隐私处理，需交接的设备类型要求维护方案覆盖交接流程），且安全测试、隐私处理、维护方案三类证据必须齐备。
- **试运行申请**：景区结合地形、客流与人员配置申请限定范围的试运行，且只能选用当前有效型号。
- **并行审查**：技术、无障碍、安全、数据保护四类审查可并行提交，结论齐全且证据仍在有效期内才可批准。
- **批准记录**：写明适用场景、人数上限和复评日期；部署受三者约束，固件版本必须与批准记录一致。
- **变更管理**：固件升级、关键零件更换、扩大使用范围必须产生新申请并重新审查，不能套用旧证书。
- **事件处置**：事故、投诉、抽检异常按严重度触发单点暂停、同型号排查或全面撤销；整改后的恢复只能来自有记录的复核，被撤销的证书不可恢复，须重新申请。
- **追溯与公开**：监管人员可从一次部署追到对应证据与审查责任人；公众查询只显示适用范围与风险提示，不暴露商业秘密。

### 示例

```python
from datetime import date
from scenic_devices.supervision import RegulatoryService, ReviewDimension

service = RegulatoryService.from_registry("data/devices.json")
service.register_model(model)                       # 厂商登记型号档案（含证据）
application_id = service.submit_application(        # 景区申请限定范围试运行
    scenic_area="云山景区", model_code="GB-100", software_version="1.0.0",
    scope=scope, on=date(2026, 9, 1),
)
for dimension in ReviewDimension:                   # 四类审查并行开展
    service.submit_review(application_id, dimension=dimension,
                          reviewer="审查责任人", passed=True, on=date(2026, 9, 1))
approval = service.approve(application_id, headcount_limit=5,
                           review_date=date(2027, 8, 31), on=date(2026, 9, 1))
deployment_id = service.deploy(approval.approval_no, unit_serial="UNIT-1",
                               zone="东门环线", firmware_version="1.0.0",
                               on=date(2026, 9, 1))
trace = service.trace_deployment(deployment_id, on=date(2026, 9, 1))  # 监管追溯
public = service.public_model_view("GB-100", on=date(2026, 9, 1))     # 公众查询
```
