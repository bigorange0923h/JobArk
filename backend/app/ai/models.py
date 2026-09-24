"""AI 配置的数据模型：OpenAI 兼容服务商与模型。

职责边界：

- 服务商持有接口基地址与**加密后的** API Key，模型只持有远端模型标识；
  同一服务商下的模型共享凭据，避免为每个模型重复录入密钥。
- 默认标记由服务层在事务中切换，并由部分唯一索引在数据库层兜底：
  应用层事务只能降低并发写入产生两个默认模型的概率，真正的"至多一个"由索引保证。
- 本表是配置记录，不承载简历、档案、职位等业务事实，也不追溯改写已生成的 AI 候选稿。
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import EditableMixin, UuidPrimaryKeyMixin


class AiProvider(UuidPrimaryKeyMixin, EditableMixin, Base):
    """OpenAI 兼容服务商配置。

    名称唯一，避免工作台出现两个无法区分的同名服务商；凭据只保存密文与展示掩码，
    明文既不入库也不出现在任何读取响应中。
    """

    __tablename__ = "ai_providers"
    __table_args__ = (UniqueConstraint("name", name="uq_ai_providers_name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="服务商显示名称；唯一。")
    base_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, comment="OpenAI 兼容接口基地址；仅允许 HTTPS 或本地回环 HTTP。"
    )
    api_key_ciphertext: Mapped[str | None] = mapped_column(
        Text, comment="API Key 的可逆密文；明文不落库，密文不返回客户端。"
    )
    api_key_mask: Mapped[str | None] = mapped_column(
        String(32), comment="仅供界面展示的末四位掩码；不含可用于调用的信息。"
    )
    description: Mapped[str | None] = mapped_column(String(500), comment="可选说明，仅用于用户记忆用途。")
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="停用后其模型不得作为默认模型，也不能被连接测试使用。",
    )


class AiModel(UuidPrimaryKeyMixin, EditableMixin, Base):
    """服务商下的一个模型配置。

    `remote_model_id` 是发送给兼容接口的模型标识，同一服务商内不可重复；
    `is_default` 由部分唯一索引约束为全局至多一行为真。
    """

    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "remote_model_id", name="uq_ai_models_provider_id_remote_model_id"),
        # 部分唯一索引：只对 is_default 为真的行生效，从而在数据库层保证"至多一个默认模型"。
        Index("uq_ai_models_default", "is_default", unique=True, postgresql_where=text("is_default")),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属服务商；服务商删除时级联清理其模型配置。",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="模型显示名称，供用户识别用途。")
    remote_model_id: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="发送给兼容接口的模型标识，同一服务商内唯一。"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), comment="停用后不再参与默认模型候选。"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="唯一默认启用标记；由部分唯一索引保证至多一行为真。",
    )
