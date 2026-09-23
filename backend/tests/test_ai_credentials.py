"""AI 凭据加密与环境边界；不访问数据库或网络。

这些测试只验证"根密钥从哪来"和"加解密与掩码是否安全"，不覆盖配置 API 的持久化行为：
密钥来源错误属于部署配置问题，必须在进程启动或首次敏感操作时立刻暴露，
而不是等到真正发送请求才发现凭据无法解密。
"""

import pytest

from app.ai.credentials import CredentialCipher, mask_secret
from app.core.config import AppEnv, Settings
from app.core.errors import ConflictError


def test_local_default_key_can_round_trip() -> None:
    """LOCAL 未显式配置根密钥时，使用开发默认值仍可完成加密往返。"""
    settings = Settings(app_env=AppEnv.LOCAL, ai_credential_encryption_key="", _env_file=None)  # pyright: ignore[reportCallIssue]
    cipher = CredentialCipher.from_settings(settings)
    assert cipher.decrypt(cipher.encrypt("sk-local")) == "sk-local"


def test_non_local_environment_requires_explicit_key() -> None:
    """TEST/PROD 缺少显式根密钥时必须安全失败，不能退回开发默认值。"""
    settings = Settings(app_env=AppEnv.TEST, ai_credential_encryption_key="", _env_file=None)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ConflictError, match="加密根密钥"):
        CredentialCipher.from_settings(settings)


def test_mask_never_contains_full_key() -> None:
    """掩码只保留末四位，且空/短值不得泄漏原文。"""
    assert mask_secret("sk-12345678") == "••••5678"
    assert mask_secret("abc") == "••••"


def test_invalid_fernet_key_maps_to_safe_error() -> None:
    """无效根密钥必须映射为安全错误，且不得回显密钥内容。"""
    settings = Settings(app_env=AppEnv.TEST, ai_credential_encryption_key="not-a-valid-key", _env_file=None)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ConflictError) as error:
        CredentialCipher.from_settings(settings)
    assert "not-a-valid-key" not in str(error.value)


def test_decrypt_failure_does_not_leak_ciphertext() -> None:
    """解密失败只返回安全提示，绝不把密文或其片段带进异常文案。"""
    settings = Settings(app_env=AppEnv.LOCAL, ai_credential_encryption_key="", _env_file=None)  # pyright: ignore[reportCallIssue]
    cipher = CredentialCipher.from_settings(settings)
    ciphertext = "gAAAAAB-not-a-real-token"
    with pytest.raises(ConflictError) as error:
        cipher.decrypt(ciphertext)
    assert ciphertext not in str(error.value)
