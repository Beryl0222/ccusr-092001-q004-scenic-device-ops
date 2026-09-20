"""设备配置读取和安全约束检查。"""

import json
from dataclasses import dataclass
from pathlib import Path


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


def load_device_classes(path: str | Path) -> dict[str, DeviceClass]:
    """读取设备类型清单，校验安全限制后按编码索引。"""
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_registry(items)
    return {
        item["code"]: DeviceClass(
            code=item["code"],
            capabilities=tuple(item["capabilities"]),
            privacy_level=item["privacy_level"],
            requires_staff_handover=bool(item["requires_staff_handover"]),
        )
        for item in items
    }
