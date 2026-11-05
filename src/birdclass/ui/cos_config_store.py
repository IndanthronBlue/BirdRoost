from __future__ import annotations

import getpass
import os
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from ..cloud_backup import normalize_prefix
from ..secret_store import (
    delete_cos_credentials,
    last_error,
    load_cos_credentials,
    save_cos_credentials,
)


@dataclass
class CosConfig:
    bucket: str = ""
    region: str = "ap-shanghai"
    endpoint: str = ""
    prefix: str = ""
    secret_id: str = ""
    secret_key: str = ""
    save_config: bool = False


def load_cos_config(settings: QSettings) -> CosConfig:
    save = settings.value("cloud_save_config", False)
    save = save if isinstance(save, bool) else str(save).lower() == "true"
    secret_id = secret_key = ""
    if save:
        secret_id, secret_key = load_cos_credentials()
    return CosConfig(
        bucket=str(settings.value("cloud_bucket", "")),
        region=str(settings.value("cloud_region", "ap-shanghai")),
        endpoint=str(settings.value("cloud_endpoint", "")),
        prefix=normalize_prefix(str(settings.value("cloud_prefix", getpass.getuser()))),
        secret_id=secret_id,
        secret_key=secret_key,
        save_config=save,
    )


def save_cos_config(settings: QSettings, config: CosConfig) -> tuple[bool, str]:
    if not config.save_config:
        for key in ("cloud_bucket", "cloud_region", "cloud_endpoint", "cloud_prefix"):
            settings.remove(key)
        settings.setValue("cloud_save_config", False)
        delete_cos_credentials()
        settings.sync()
        return True, "已取消保存 COS 配置"
    settings.setValue("cloud_save_config", True)
    settings.setValue("cloud_bucket", config.bucket.strip())
    settings.setValue("cloud_region", config.region.strip())
    settings.setValue("cloud_endpoint", config.endpoint.strip())
    settings.setValue("cloud_prefix", normalize_prefix(config.prefix))
    settings.sync()
    if config.secret_id.strip() and config.secret_key.strip():
        if not save_cos_credentials(config.secret_id, config.secret_key):
            return False, f"COS 配置保存失败：{last_error()}"
        return True, "COS 配置已保存到 macOS 钥匙串"
    return True, "COS 配置已保存"


def resolve_credentials(config: CosConfig) -> tuple[str, str]:
    secret_id = config.secret_id.strip() or os.environ.get("TENCENTCLOUD_SECRET_ID", "") or os.environ.get("COS_SECRET_ID", "")
    secret_key = config.secret_key.strip() or os.environ.get("TENCENTCLOUD_SECRET_KEY", "") or os.environ.get("COS_SECRET_KEY", "")
    return secret_id, secret_key


def config_summary(config: CosConfig) -> str:
    if not config.bucket.strip():
        return "未配置 COS，请先在“配置…”中填写桶名、地域和 Secret。"
    parts = [config.bucket.strip(), config.region.strip()]
    if config.prefix.strip():
        parts.append(f"users/{normalize_prefix(config.prefix)}/")
    return " · ".join(part for part in parts if part)
