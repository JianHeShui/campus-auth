"""凭据持久化：环境变量优先，其次用户配置目录下的凭据文件。

注意：密码需要以明文提交给门户，本工具在本地保存时也是明文（无法避免）。
请确保凭据文件仅自己可读，且不要纳入版本控制。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .client import Credentials

_ENV_USER = "CAMPUS_USERNAME"
_ENV_PASS = "CAMPUS_PASSWORD"
_ENV_SERVICE = "CAMPUS_SERVICE"

CONFIG_DIR = Path(os.environ.get("CAMPUS_AUTH_HOME", Path.home() / ".campus-auth"))
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"


class ConfigError(RuntimeError):
    """凭据缺失或无法读取。"""


def load_credentials(path: Path | None = None) -> Credentials:
    """环境变量优先，否则读凭据文件。"""
    username = os.environ.get(_ENV_USER, "").strip()
    password = os.environ.get(_ENV_PASS, "")
    service = os.environ.get(_ENV_SERVICE, "").strip()

    if username and password:
        return Credentials(username, password, service)

    file = path or CREDENTIALS_FILE
    if file.exists():
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"凭据文件无法解析: {exc}") from exc
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        service = str(data.get("service", "")).strip()
        if username and password:
            return Credentials(username, password, service)

    raise ConfigError(
        f"未找到凭据。请设置环境变量 {_ENV_USER}/{_ENV_PASS}，"
        f"或先运行 `campus-auth configure` 保存凭据。"
    )


def save_credentials(credentials: Credentials, path: Path | None = None) -> Path:
    file = path or CREDENTIALS_FILE
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    payload = {
        "username": credentials.username,
        "password": credentials.password,
        "service": credentials.service,
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, file)
    try:
        os.chmod(file, 0o600)  # 尽量限制为仅本人可读（Windows 上尽力而为）
    except OSError:
        pass
    return file
