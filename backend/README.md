# Backend

JobArk 后端是位于本目录的独立 Python 工程，工程根即 `backend/`：

- `pyproject.toml`、`uv.lock`：依赖与解释器版本声明（`requires-python >= 3.14`）。
- `app/main.py`：唯一 FastAPI 入口，`create_app()` 负责组装应用，模块级 `app` 供 ASGI 服务器引用。
- `app/core/`：配置、结构化日志、请求标识、统一响应与异常契约，以及异步数据库引擎与会话依赖；决策细节见 `docs/adr/0001-统一响应与异常契约.md` 与 `docs/adr/0002-数据库异步访问与迁移约定.md`。
- `app/modules/<domain>/`：按业务领域组织的模块，聚合自身的 router、service、repository、models 与 schemas。
- `app/ai/`：受控 LLM 能力层；只能产出候选草稿，不得写入业务事实。
- `app/automation/`：浏览器自动化端口与适配器，V1 仅保留只读能力与人工确认流程。
- `alembic.ini`、`migrations/`：Alembic 迁移；业务表结构只能通过迁移变更。配置文件必须保持 ASCII-only（原因见 ADR 0002）。
- `tests/`：HTTP 契约测试与数据库集成测试；未配置测试库时后者自动跳过。
- `.env.example`：应用配置示例，复制为 `backend/.env` 后使用。

## 本地运行

使用 `uv`：

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

未安装 `uv` 时，可用标准库虚拟环境替代（本机 Python 3.14 通过 `py -3.14` 调用）：

```bash
cd backend
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install fastapi uvicorn pydantic-settings
.venv\Scripts\python -m uvicorn app.main:app --reload
```

启动后访问 `http://127.0.0.1:8000/health` 自检，`/docs` 查看 OpenAPI 文档。

## 配置

应用配置从环境变量与 `backend/.env` 读取，统一使用 `JOBARK_` 前缀：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `JOBARK_APP_ENV` | `local` | 运行环境标识：`local`、`test`、`prod` |
| `JOBARK_LOG_LEVEL` | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |
| `JOBARK_API_V1_PREFIX` | `/api/v1` | 业务领域路由的挂载前缀 |
| `JOBARK_DATABASE_URL` | 本地占位串 | 异步连接串，驱动固定为 `asyncpg`；密码需与仓库根目录 `.env` 的 `POSTGRES_PASSWORD` 一致 |
| `JOBARK_DATABASE_ECHO` | `false` | 是否把 SQL 语句写入日志，仅本地排查使用 |

仓库根目录的 `.env` 仅供 `compose.yaml` 使用（`POSTGRES_*`），后端不读取它。`.env` 按进程工作目录解析，因此请在 `backend/` 目录下启动服务。

## 数据库迁移

```bash
cd backend
uv run alembic upgrade head                              # 升级到最新版本
uv run alembic downgrade base                            # 回退到基线
uv run alembic revision --rev-id 0002 -m "新增 xxx 表"    # 新建迁移（编号递增、可读）
```

- 连接串从 `JOBARK_DATABASE_URL` 读取，不写入 `alembic.ini`，凭据不进版本库。
- 新增领域模块后必须在 `migrations/env.py` 中显式导入其 `models`，否则 autogenerate 会静默漏表。

## 测试

```bash
cd backend
uv run pytest     # 契约与集成测试；警告即失败
uv run pyright    # 类型检查（strict），用于拦住漏写 await 等问题
```

数据库集成测试需要独立测试库，通过环境变量提供；未设置时自动跳过，不影响其余测试：

```bash
set JOBARK_TEST_DATABASE_URL=postgresql+asyncpg://jobark_app:<本地密码>@127.0.0.1:5432/jobark_test
uv run pytest
```

测试库会被自动创建，且迁移测试会执行 `downgrade base`，因此**必须与开发库分离**。

当前覆盖：健康检查的成功包装、请求标识的透传与非法值防护、404/405/422/500 的错误码与信息泄露边界、结构化日志字段与请求关联、迁移的 upgrade/downgrade 可重复性、请求级会话的连接正确性，以及数据库不可用时服务仍能启动。

## 接口契约

- 成功响应 `{success: true, data, meta}`；失败响应 `{success: false, error, meta}`；分页等附加信息放入 `meta`。
- 所有响应携带 `X-Request-ID` 响应头；入站 `X-Request-ID` 通过白名单校验后沿用，否则生成新标识。
- 业务领域路由挂 `/api/v1`；`/health` 保持根路径且不随版本变化。
- 领域代码抛出 `AppError` 子类，异常由统一处理器映射为稳定错误码；禁止在路由中 `try/except` 兜底或返回裸字符串。
- 日志为单行 JSON；`uvicorn.access` 已关闭，访问日志由中间件统一产出以保证带 `request_id`。

> 当前仅有 `/health` 一个接口：阶段 0 剩余工作为前端工程（含 API Client）与 CI 质量工具链（Pyright 已就位，缺 Ruff 与 CI 配置）。

## 边界

后端是业务事实的唯一权威来源：数据库保存领域数据，LLM、浏览器会话与前端状态都不能作为唯一事实来源。所有会引起外部副作用的操作都必须有显式确认与审计记录。
