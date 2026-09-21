# JobArk PostgreSQL 镜像

本镜像基于固定补丁版本的官方 PostgreSQL 18.6 镜像，并在首次初始化 `jobark` 数据库时启用：

- `pgcrypto`：UUID 等通用加密函数；
- `pg_trgm`：职位标题、公司名和关键词的模糊检索；
- `unaccent`：中文/多语言检索场景中的文本规范化辅助。

业务表结构、索引和数据必须由 Alembic 迁移管理，不能写入初始化 SQL。镜像不预装 pgvector：当前 V1 不使用向量/RAG；未来若有经验证的需求，应新增独立 ADR、镜像版本和迁移，而非静默改变现有环境。

## 本地使用

1. 将项目根目录的 `.env.example` 复制为 `.env`，并设置强密码。
2. 运行 `docker compose -f deploy/docker-compose.yml up -d --build`。
3. 使用 `docker compose -f deploy/docker-compose.yml ps` 确认 `postgres` 为 healthy。

数据库仅绑定在 `127.0.0.1`，不直接暴露到局域网或公网。数据保存在命名卷 `jobark_postgres_data`；删除容器不会删除该卷。
