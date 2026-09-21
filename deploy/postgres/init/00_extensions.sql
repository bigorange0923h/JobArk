-- 只初始化 V1 已知需要的通用能力；业务表、索引和数据变更必须通过 Alembic 迁移管理。
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
