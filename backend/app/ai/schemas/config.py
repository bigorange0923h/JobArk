"""AI 模型配置接口的请求与响应 DTO。

读取 DTO 是**白名单**：只暴露可展示字段，绝不包含 API Key 明文或密文；
凭据字段只出现在写入请求里，且 `None` 与空字符串的语义都是"保持已有密文不变"，
因此接口无法通过提交空值意外清空已保存的 Key。

更新请求统一携带 `version`：它与数据库乐观锁列比对，不一致返回 409，
避免两个页面各自基于旧快照覆盖对方的改动。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.responses import EditableRead


class _StrictRequest(BaseModel):
    """请求基类：拒绝未知字段。

    为什么必须拒绝：请求里多出的字段（尤其是 `api_key_ciphertext` 之类的内部名）
    若被静默忽略，调用方会以为设置生效，实际却没写入，属于难以排查的静默失败。
    """

    model_config = ConfigDict(extra="forbid")


class ModelRead(EditableRead):
    """模型读取 DTO；不含任何凭据字段。"""

    provider_id: UUID = Field(description="所属服务商主键。")
    name: str = Field(description="模型显示名称。")
    remote_model_id: str = Field(description="发送给 OpenAI 兼容接口的模型标识。")
    is_enabled: bool = Field(description="是否参与默认模型候选。")
    is_default: bool = Field(description="是否为当前唯一默认模型。")


class ProviderRead(EditableRead):
    """服务商读取 DTO；只暴露"是否已配置"与固定掩码。"""

    name: str = Field(description="服务商显示名称。")
    base_url: str = Field(description="OpenAI 兼容接口基地址。")
    api_key_configured: bool = Field(description="是否已保存 API Key；不暴露任何凭据内容。")
    api_key_mask: str | None = Field(description="供界面展示的固定掩码；未配置凭据时为 null。")
    description: str | None = Field(description="可选说明。")
    is_enabled: bool = Field(description="停用后其模型不得作为默认模型。")
    has_default_model: bool = Field(description="其下是否存在默认模型；用于阻止停用或删除。")
    models: list[ModelRead] = Field(default_factory=list[ModelRead], description="该服务商下的模型配置。")


class DeletedRead(BaseModel):
    """删除结果：只返回被删除记录的主键。"""

    id: UUID = Field(description="被删除记录的主键。")


class ConnectionTestRead(BaseModel):
    """连接测试结果；不包含上游响应原文或任何凭据。"""

    ok: bool = Field(description="最小协议请求是否成功。")


class DeleteConfirm(_StrictRequest):
    """删除确认：删除配置不可恢复，必须显式确认。"""

    confirmed: bool = Field(description="用户已确认删除；未确认为 422。")


class ProviderCreate(_StrictRequest):
    """创建服务商。"""

    name: str = Field(min_length=1, max_length=100, description="服务商显示名称；全局唯一。")
    base_url: str = Field(min_length=1, max_length=2048, description="仅允许 HTTPS 或本地回环 HTTP。")
    api_key: str | None = Field(
        default=None,
        max_length=4096,
        description="API Key 明文；只在创建或替换时提交，留空表示暂不配置凭据。",
    )
    description: str | None = Field(default=None, max_length=500, description="可选说明。")


class ProviderUpdate(_StrictRequest):
    """局部更新服务商；未提交的字段保持原值。"""

    version: int = Field(ge=1, description="乐观锁版本号，必须原样回传。")
    name: str | None = Field(default=None, min_length=1, max_length=100, description="新的显示名称。")
    base_url: str | None = Field(default=None, min_length=1, max_length=2048, description="新的接口基地址。")
    api_key: str | None = Field(
        default=None,
        max_length=4096,
        description="新的 API Key；省略或留空表示保留已有密文，不会清空凭据。",
    )
    description: str | None = Field(default=None, max_length=500, description="新的说明；显式传 null 表示清空。")
    is_enabled: bool | None = Field(default=None, description="是否启用；停用前必须没有默认模型。")


class ModelCreate(_StrictRequest):
    """创建模型；模型不携带 API Key，凭据始终来自所属服务商。"""

    name: str = Field(min_length=1, max_length=100, description="模型显示名称。")
    remote_model_id: str = Field(min_length=1, max_length=200, description="发送给兼容接口的模型标识。")
    is_enabled: bool = Field(default=True, description="是否启用。")


class ModelUpdate(_StrictRequest):
    """局部更新模型；未提交的字段保持原值。"""

    version: int = Field(ge=1, description="乐观锁版本号，必须原样回传。")
    name: str | None = Field(default=None, min_length=1, max_length=100, description="新的显示名称。")
    remote_model_id: str | None = Field(
        default=None, min_length=1, max_length=200, description="新的远端模型标识；同一服务商内唯一。"
    )
    is_enabled: bool | None = Field(default=None, description="是否启用；默认模型不能被直接停用。")
