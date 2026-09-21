# 使用已验证的官方 PostgreSQL 16 镜像摘要，避免浮动标签导致本地环境不可复现。
# JobArk V1 不需要向量检索；如未来确有需求，应通过 ADR、独立镜像版本和迁移引入 pgvector。
FROM postgres:16-bookworm@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67

LABEL org.opencontainers.image.title="JobArk PostgreSQL"
LABEL org.opencontainers.image.description="JobArk 的 PostgreSQL 16 数据库镜像，初始化通用文本检索与安全扩展。"

# 初始化脚本只在空数据卷首次创建数据库时执行；业务表结构由 Alembic 管理。
COPY init/00_extensions.sql /docker-entrypoint-initdb.d/00_extensions.sql
