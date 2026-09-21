# JobArk PostgreSQL 镜像

本镜像基于已固定摘要的官方 PostgreSQL 16 镜像，并在首次初始化 `jobark` 数据库时启用：

- `pgcrypto`：UUID 等通用加密函数；
- `pg_trgm`：职位标题、公司名和关键词的模糊检索；
- `unaccent`：中文/多语言检索场景中的文本规范化辅助。

业务表结构、索引和数据必须由 Alembic 迁移管理，不能写入初始化 SQL。JobArk V1 不创建或使用 `vector` 扩展；未来若有经验证的向量检索需求，应新增独立 ADR、镜像版本和迁移，而非静默改变现有环境。

## 本地使用

1. 将项目根目录的 `.env.example` 复制为 `.env`，并设置本地开发密码。
2. 从项目根目录运行 `docker compose up -d --build postgres`。
3. 使用 `docker compose ps` 确认 `postgres` 为 healthy。

`compose.yaml` 与 `.env` 均位于项目根目录，因此 Docker Compose 会自动读取本地配置。通过 IDE 启动时，应将 Compose 文件设置为 `D:\Dev\projects\JobArk\compose.yaml`。

数据库仅绑定在 `127.0.0.1`，不直接暴露到局域网或公网。数据保存在命名卷 `jobark_postgres_data`；删除容器不会删除该卷。
