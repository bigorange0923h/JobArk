# Backend

JobArk 后端是位于本目录的独立 Python 工程，工程根即 `backend/`：

- `pyproject.toml`、`uv.lock`：依赖与解释器版本声明（`requires-python >= 3.14`）。
- `app/main.py`：唯一 FastAPI 入口，`create_app()` 负责组装应用，模块级 `app` 供 ASGI 服务器引用。
- `app/core/`：配置、数据库、日志与统一响应/异常契约。
- `app/modules/<domain>/`：按业务领域组织的模块，聚合自身的 router、service、repository、models 与 schemas。
- `app/ai/`：受控 LLM 能力层；只能产出候选草稿，不得写入业务事实。
- `app/automation/`：浏览器自动化端口与适配器，V1 仅保留只读能力与人工确认流程。
- `migrations/`：Alembic 迁移；业务表结构只能通过迁移变更。
- `tests/`：测试。

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
.venv\Scripts\python -m pip install fastapi uvicorn
.venv\Scripts\python -m uvicorn app.main:app --reload
```

启动后访问 `http://127.0.0.1:8000/health` 自检，`/docs` 查看 OpenAPI 文档。

> 当前仅实现健康检查接口。统一响应包装（`success`/`data`/`meta`）、异常处理、数据库接入与前端工程属于阶段 0 的后续工作项。

## 边界

后端是业务事实的唯一权威来源：数据库保存领域数据，LLM、浏览器会话与前端状态都不能作为唯一事实来源。所有会引起外部副作用的操作都必须有显式确认与审计记录。
