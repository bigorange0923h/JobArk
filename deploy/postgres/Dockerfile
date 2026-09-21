# 使用已固定补丁版本的官方 PostgreSQL 镜像，避免开发环境因浮动标签产生不可复现构建。
FROM postgres:18.6-bookworm

LABEL org.opencontainers.image.title="JobArk PostgreSQL"
LABEL org.opencontainers.image.description="JobArk 的 PostgreSQL 18 数据库镜像，初始化通用文本检索与安全扩展。"

# 初始化脚本只在空数据卷首次创建数据库时执行；业务表结构由 Alembic 管理。
COPY init/00_extensions.sql /docker-entrypoint-initdb.d/00_extensions.sql
