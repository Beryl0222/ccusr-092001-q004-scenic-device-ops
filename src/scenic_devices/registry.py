"""设备配置读取和安全约束检查。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceClass:
    code: str
    capabilities: tuple[str, ...]
    privacy_level: str
    requires_staff_handover: bool


def validate_registry(items: list[dict]) -> None:
    codes = [item["code"] for item in items]
    if len(codes) != len(set(codes)):
        raise ValueError("设备类型编码重复")
    for item in items:
        if "recording" in item["capabilities"] and item["privacy_level"] == "none":
            raise ValueError("具备影像能力的设备必须声明隐私等级")
