"""AI 服务商凭据的可逆加密与安全掩码。

API Key 需要以可逆密文入库，供服务端在真实请求前解密；但明文与密文都不得进入
API 响应、日志或异常文案。本模块只负责"根密钥解析、加解密、掩码"三件事，
不接触数据库、配置接口或外部 HTTP，使凭据边界保持单一职责。

根密钥来源固定在 `from_settings` 一处判断：LOCAL 允许代码内开发默认值，
TEST/PROD 必须由 `JOBARK_AI_CREDENTIAL_ENCRYPTION_KEY` 显式提供，缺失即安全失败。
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import AppEnv, Settings
from app.core.errors import ConflictError

# 仅用于 LOCAL 的开发默认密钥：固定盐的 SHA-256 摘要经 URL-safe base64 编码，
# 使本地开发无需手工配置即可完成加密往返。该值写死在代码里、不具任何机密性，
# 因此禁止用于 TEST/PROD（由 `from_settings` 的环境判断保证）。
_DEV_KEY_SALT = b"jobark-local-ai-credential-encryption-key-v1"
_MISSING_KEY_MESSAGE = "未配置 AI 凭据加密根密钥。"
_INVALID_KEY_MESSAGE = "AI 凭据加密根密钥无效，请检查 JOBARK_AI_CREDENTIAL_ENCRYPTION_KEY。"
_DECRYPT_FAILED_MESSAGE = "AI 凭据无法解密，请重新保存服务商 API Key。"


def _dev_default_key() -> str:
    """由固定开发盐派生 LOCAL 默认根密钥。

    返回:
        str: Fernet 要求的 32 字节 URL-safe base64 密钥字符串。
    """
    return base64.urlsafe_b64encode(hashlib.sha256(_DEV_KEY_SALT).digest()).decode("ascii")


def mask_secret(value: str) -> str:
    """生成仅供界面显示的固定掩码，绝不返回完整凭据。

    参数:
        value: 凭据原文；仅用于截取末四位，不参与其他判断。

    返回:
        str: 形如 `••••5678` 的掩码；不足四位时只返回固定前缀。
    """
    return "••••" + value[-4:] if len(value) >= 4 else "••••"


@dataclass(frozen=True)
class CredentialCipher:
    """服务商凭据的加解密器。

    实例只持有 Fernet 句柄，不暴露根密钥。调用方必须通过 `from_settings` 构造，
    使"根密钥从哪来、当前环境是否允许开发默认值"只有一处判断。
    """

    _fernet: Fernet

    @classmethod
    def from_settings(cls, settings: Settings) -> CredentialCipher:
        """按运行环境解析根密钥并构造加密器。

        参数:
            settings: 应用配置；根密钥从 `ai_credential_encryption_key` 读取。

        返回:
            CredentialCipher: 可用于加解密凭据的实例。

        异常:
            ConflictError: 非 LOCAL 环境缺少根密钥，或根密钥不是合法 Fernet 密钥。
        """
        key = settings.ai_credential_encryption_key.get_secret_value()
        if not key:
            if settings.app_env is not AppEnv.LOCAL:
                raise ConflictError(_MISSING_KEY_MESSAGE)
            key = _dev_default_key()
        try:
            return cls(Fernet(key.encode("ascii")))
        except (ValueError, TypeError) as error:
            # 刻意不回显密钥内容：错误文案会进入响应，密钥不得出现在任何对外文本中。
            raise ConflictError(_INVALID_KEY_MESSAGE) from error

    def encrypt(self, value: str) -> str:
        """加密凭据明文。

        参数:
            value: 待加密的 API Key 明文。

        返回:
            str: ASCII 密文，可直接存入数据库文本列。
        """
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """解密数据库中的凭据密文。

        参数:
            ciphertext: `encrypt` 产出的密文。

        返回:
            str: 原始 API Key 明文。

        异常:
            ConflictError: 密文损坏或根密钥已更换；异常文案不含密文或根密钥。
        """
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as error:
            # 解密失败最常见的成因是根密钥被更换；修复方式是重新保存 API Key，
            # 因此这里给出可操作的安全提示，而不是暴露密文或密钥。
            raise ConflictError(_DECRYPT_FAILED_MESSAGE) from error
