# 复制 JD 主入口与渠道、公司资料验证

## 改动范围

需求见 `requirements/job-intake-and-submission.md`。本次实现阶段一的手工渠道、公司介绍及补全字段，复用原有 JD 保存、平台 HTML 候选提取和匹配流程。`channel_name` 是用户声明，手工记录的 `source` 仍为 MANUAL，不证明平台访问。旧记录不回填猜测渠道。

迁移 0013 增加两列：`job_postings.channel_name` 与 `companies.description`。存在非空新增内容时拒绝降级，避免静默丢失业务资料。仅在随机 schema 验证迁移，未升级日常开发业务 schema。

## 自动检查

- 后端：`uv run pytest tests/test_job_api.py tests/test_job_boundaries.py tests/test_job_import_api.py tests/test_job_import_migration.py tests/test_migrations.py -q`，48 passed。随后增加迁移数据保护用例并重跑 `tests/test_job_import_migration.py`，7 passed。测试使用随机 schema 隔离，并包含真实 PostgreSQL 迁移升级、回退及 Alembic 模型差异检查。
- 后端 Ruff、格式检查和 Pyright 通过；Pyright 0 errors。新增迁移用例随后通过 Ruff 和格式检查。
- 前端职位列表、详情及导入组件回归：列表 8、详情 8、导入 16 项通过，合计 32 项。新增渠道导致旧雇佣类型测试按第一个 AutoComplete 错取组件，已改为按业务控件定位并重跑通过。
- 前端 `npm run lint` 和 `npm run build` 通过；构建包含 TypeScript 检查。最后新增详情断言未修改生产代码。
- `git diff --check` 通过。

## 尚未验证

- 浏览器实际操作及视觉验收未执行。
- 自动采集、调度和自动投递未接通，本次没有向招聘方发送内容。
- GitHub Issue 创建返回 403 `Resource not accessible by integration`，无法同步协作状态；本文件仅记录验证证据，不替代 Issue 状态。
