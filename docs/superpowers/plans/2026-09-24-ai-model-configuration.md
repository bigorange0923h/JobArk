# AI 模型配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让单人用户在工作台维护多个 OpenAI 兼容服务商和模型，安全保存服务商 API Key，并让既有 AI 候选功能使用唯一默认模型。

**Architecture:** 新增 `app.ai` 内聚的模型、仓储、服务、路由和凭据加密模块。服务商保存接口基地址与加密凭据，模型保存远端模型标识与默认状态；网关先读取默认模型的不可变请求配置、结束数据库事务，再发起一次受限的 OpenAI 兼容 HTTP 请求。前端仅消费掩码 DTO，通过独立 AI 配置页面管理服务商和模型。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy async、Alembic、PostgreSQL 部分唯一索引、`cryptography` 的 Fernet、Vue 3、TypeScript、Ant Design Vue、Vitest、Pytest。

---

## 文件结构

- Create: `backend/app/ai/models.py` — `AiProvider` 与 `AiModel` 的持久化模型及数据库约束。
- Create: `backend/app/ai/schemas.py` — 配置 API 的请求/响应 DTO；读取模型不包含 API Key 密文。
- Create: `backend/app/ai/repository.py` — 局限于配置表的查询、加锁与持久化辅助。
- Create: `backend/app/ai/credentials.py` — 根密钥解析、Fernet 加解密和安全掩码。
- Create: `backend/app/ai/service.py` — 服务商/模型生命周期、默认模型选择和连接测试编排。
- Create: `backend/app/ai/router.py` — `/api/v1/ai` 的受控配置接口。
- Create: `backend/migrations/versions/0008_ai_model_configuration.py` — 两张配置表和部分唯一默认模型索引。
- Create: `backend/tests/test_ai_credentials.py` — 无数据库的加密与环境边界测试。
- Create: `backend/tests/test_ai_config_api.py` — 隔离 PostgreSQL 上的配置 API、状态与凭据回显测试。
- Modify: `backend/pyproject.toml`, `backend/uv.lock` — 锁定 `cryptography`。
- Modify: `backend/app/core/config.py` — 增加 `ai_credential_encryption_key`，保留旧网关变量仅用于迁移期兼容。
- Modify: `backend/app/main.py`, `backend/migrations/env.py`, `backend/tests/conftest.py` — 挂载路由、导入元数据并在测试清表清理新表。
- Modify: `backend/app/ai/llm/gateway.py` — 使用已解析的默认模型，发送 OpenAI 兼容 JSON 请求并安全解析结果。
- Modify: `backend/app/modules/job/parsing.py`, `backend/app/modules/profile/import_service.py`, `backend/app/modules/profile/import_router.py`, `backend/app/modules/resume/optimization.py` — 在读取默认配置后、外部请求前结束数据库事务。
- Modify: `backend/tests/test_ai_gateway.py`, `backend/tests/test_ai_flows.py`, `backend/tests/test_profile_import.py` — 更新网关调用契约与默认模型缺失路径。
- Create: `frontend/src/shared/api/ai.ts` 与 `frontend/src/shared/api/ai.test.ts` — AI 配置 DTO 和 API 封装。
- Create: `frontend/src/features/ai/AiModelConfigView.vue` 与 `frontend/src/features/ai/AiModelConfigView.test.ts` — 读取、空态、表单、确认删除、默认切换和测试连接页面。
- Modify: `frontend/src/app/router.ts`, `frontend/src/app/router.test.ts`, `frontend/src/app/NavIcon.vue` — 添加实际路由、导航项和 `ai` 图标。
- Modify: `docs/ai-gateway.md`, `docs/architecture.md`, `docs/data-model.md`, `backend/.env.example` — 把最终实现契约、数据模型和根密钥配置例子与代码保持一致。

### Task 1: 建立凭据加密与运行期配置边界

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/ai/credentials.py`
- Create: `backend/tests/test_ai_credentials.py`

- [ ] **Step 1: 写失败的加密与环境边界测试**

```python
def test_local_default_key_can_round_trip() -> None:
    settings = Settings(app_env=AppEnv.LOCAL, _env_file=None)  # pyright: ignore[reportCallIssue]
    cipher = CredentialCipher.from_settings(settings)
    assert cipher.decrypt(cipher.encrypt("sk-local")) == "sk-local"


def test_non_local_environment_requires_explicit_key() -> None:
    settings = Settings(app_env=AppEnv.TEST, _env_file=None)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ConflictError, match="加密根密钥"):
        CredentialCipher.from_settings(settings)


def test_mask_never_contains_full_key() -> None:
    assert mask_secret("sk-12345678") == "••••5678"
```

- [ ] **Step 2: 运行测试，确认因模块尚不存在而失败**

Run: `cd backend; uv run pytest tests/test_ai_credentials.py -v`

Expected: collection error for `app.ai.credentials`.

- [ ] **Step 3: 增加锁定依赖与最小凭据实现**

在 `pyproject.toml` 的运行期依赖增加 `cryptography>=46.0,<47`，执行 `uv lock`。在配置中声明：

```python
ai_credential_encryption_key: SecretStr = SecretStr("")
```

在 `credentials.py` 定义 `CredentialCipher`，仅暴露 `from_settings`、`encrypt`、`decrypt` 与 `mask_secret`。`LOCAL` 默认 key 用固定开发盐的 SHA-256 摘要经 URL-safe base64 编码生成；`TEST` 和 `PROD` 为空时抛出 `ConflictError("未配置 AI 凭据加密根密钥。")`。无效 Fernet key 同样映射为该安全错误，密文解密异常不得包含密文内容。

```python
def mask_secret(value: str) -> str:
    """生成仅供界面显示的固定掩码，绝不返回完整凭据。"""
    return "••••" + value[-4:] if len(value) >= 4 else "••••"
```

- [ ] **Step 4: 运行凭据测试，确认通过**

Run: `cd backend; uv run pytest tests/test_ai_credentials.py -v`

Expected: 3 passed.

- [ ] **Step 5: 提交凭据基础设施**

```powershell
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/app/ai/credentials.py backend/tests/test_ai_credentials.py
git commit -m "AI：新增凭据加密基础设施"
```

### Task 2: 建立服务商/模型数据模型与真实迁移

**Files:**
- Create: `backend/app/ai/models.py`
- Modify: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0008_ai_model_configuration.py`
- Modify: `backend/tests/conftest.py`
- Modify: `docs/data-model.md`
- Test: `backend/tests/test_migrations.py`

- [ ] **Step 1: 为迁移产物写失败测试**

在 `test_migrations.py` 添加断言，升级到 head 后数据库拥有 `ai_providers`、`ai_models`，并查询索引定义验证默认模型是部分唯一索引：

```python
async def test_ai_model_schema_has_single_default_index(migrated_engine: AsyncEngine) -> None:
    async with migrated_engine.connect() as connection:
        rows = (await connection.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename = 'ai_models'"))).scalars()
    assert any("UNIQUE" in item and "is_default" in item for item in rows)
```

- [ ] **Step 2: 在隔离库运行测试，确认缺表/索引失败**

在 `backend/` 目录运行下面的凭据片段与测试。片段把仓库根 `.env` 的 `POSTGRES_*` 读进内存变量用于拼接 URL，**不打印密码**，也不会输出连接串：

```powershell
# 仓库公共根：`--git-common-dir` 在链接工作树中指向主工作树的 .git，
# 因此总能找到"只存在于主工作树"的仓库根 .env。
# 不能用 `..\.env`：在 `.worktrees/<name>/backend/` 下它指向不存在的 `.worktrees/<name>/.env`。
$commonDir = (git rev-parse --path-format=absolute --git-common-dir).Trim()
$repoRoot = Split-Path -Parent $commonDir
$jobarkEnv = @{}
Get-Content (Join-Path $repoRoot '.env') | ForEach-Object { if ($_ -match '^(POSTGRES_(?:USER|PASSWORD|PORT))=(.*)$') { $jobarkEnv[$matches[1]] = $matches[2] } }
if (-not $jobarkEnv['POSTGRES_USER'] -or -not $jobarkEnv['POSTGRES_PASSWORD']) { throw "未在 $repoRoot\.env 找到 POSTGRES_USER/POSTGRES_PASSWORD" }
$port = $jobarkEnv['POSTGRES_PORT']; if (-not $port) { $port = '5432' }
$env:JOBARK_TEST_DATABASE_URL = "postgresql+asyncpg://$($jobarkEnv['POSTGRES_USER']):$($jobarkEnv['POSTGRES_PASSWORD'])@127.0.0.1:$port/jobark_test"
$env:JOBARK_AI_CREDENTIAL_ENCRYPTION_KEY = uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
uv run pytest tests/test_migrations.py::test_ai_model_schema_has_single_default_index -v
```

Expected: FAIL，因为迁移 `0008` 尚不存在。不得把 URL 指向开发数据库。

**注意：本片段是后续所有 `jobark_test` 命令的唯一来源。** Task 3、Task 4 与 Task 6 的测试与门禁都依赖同一个 shell 中的 `JOBARK_TEST_DATABASE_URL`；若中途换了新 shell，先重跑本片段（Task 6 的门禁块已内嵌同一份片段，可独立运行）。

- [ ] **Step 3: 写模型与迁移**

`AiProvider` 继承 `UuidPrimaryKeyMixin, EditableMixin, Base`，字段为 `name`（唯一）、`base_url`、`api_key_ciphertext`（nullable）、`api_key_mask`（nullable）、`description`（nullable）、`is_enabled`。`AiModel` 同样可编辑，字段为 `provider_id`（`ondelete="CASCADE"`）、`name`、`remote_model_id`、`is_enabled`、`is_default`。

```python
__table_args__ = (
    UniqueConstraint("provider_id", "remote_model_id", name="uq_ai_models_provider_id_remote_model_id"),
    Index("uq_ai_models_default", "is_default", unique=True, postgresql_where=text("is_default")),
)
```

手写 `0008` 的 `upgrade`/`downgrade`，含外键、唯一约束、普通查询索引与上述部分唯一索引。将 `from app.ai import models as ai_models` 加入 Alembic 元数据导入；把 `ai_models`、`ai_providers` 加到测试截断清单，先截断子表。

- [ ] **Step 4: 运行迁移与 schema 测试，确认通过**

Run: `cd backend; uv run pytest tests/test_migrations.py -v`，在刚执行凭据片段的同一 shell 中。若换了新 shell，先重跑 Task 2 Step 2 的片段（它会设置 `JOBARK_TEST_DATABASE_URL`）。

Expected: 全部迁移测试通过，且隔离库已升级到 `0008`。

- [ ] **Step 5: 提交数据结构**

```powershell
git add backend/app/ai/models.py backend/migrations/env.py backend/migrations/versions/0008_ai_model_configuration.py backend/tests/conftest.py backend/tests/test_migrations.py docs/data-model.md
git commit -m "AI：新增服务商和模型配置迁移"
```

### Task 3: 实现配置 API、默认状态和连接测试

**Files:**
- Create: `backend/app/ai/schemas.py`
- Create: `backend/app/ai/repository.py`
- Create: `backend/app/ai/service.py`
- Create: `backend/app/ai/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_ai_config_api.py`

- [ ] **Step 1: 写失败的 API 集成测试**

覆盖下列行为，每个断言都通过 `db_client` 请求真实迁移表：

```python
def test_first_model_is_default_and_key_is_never_returned(db_client: TestClient) -> None:
    provider = db_client.post("/api/v1/ai/providers", json={
        "name": "本地兼容服务", "base_url": "http://localhost:11434/v1", "api_key": "secret-value"
    })
    model = db_client.post(f"/api/v1/ai/providers/{provider.json()['data']['id']}/models", json={
        "name": "本地模型", "remote_model_id": "qwen3"
    })
    assert model.status_code == 201
    assert model.json()["data"]["is_default"] is True
    assert "api_key" not in provider.json()["data"]
    assert provider.json()["data"]["api_key_mask"] == "••••alue"
```

另写：第二模型不会自动默认、切换默认原子地清除旧标记、禁止停用/删除唯一默认模型、禁用服务商不能保有默认模型、同服务商远端 ID 冲突为 409、读取响应不含 `ciphertext`、不安全 URL 为 422、空/替换 API Key 语义正确、连接失败不修改数据。

- [ ] **Step 2: 运行 API 测试，确认因为路由不存在而失败**

Run: `cd backend; uv run pytest tests/test_ai_config_api.py -v`，在刚执行凭据片段的同一 shell 中；若换了新 shell，先重跑 Task 2 Step 2 的片段。

Expected: FAIL with 404 or collection error; failure must not be a test database setup error.

- [ ] **Step 3: 实现 DTO、仓储、服务和路由**

请求模型采用 `extra="forbid"` 与明确长度：服务商创建/更新支持 `api_key: str | None`（更新中 `None` 表示不改），模型创建/更新不携带 API Key。服务商读取 DTO 含 `api_key_configured: bool`、`api_key_mask: str | None` 和 `has_default_model: bool`；模型读取 DTO 含 `is_default`，两者均不含凭据密文。

服务层必须使用一次事务完成默认模型变更：创建第一个启用模型时设默认；`set_default_model` 先锁定当前默认行和目标行，再清除旧默认、设置目标、`commit`。对 `IntegrityError` 回滚并映射 `ConflictError`，不把 PostgreSQL 错误返回用户。

路由表至少包含：

```text
GET    /ai/providers
POST   /ai/providers
PATCH  /ai/providers/{provider_id}
DELETE /ai/providers/{provider_id}
POST   /ai/providers/{provider_id}/models
PATCH  /ai/models/{model_id}
POST   /ai/models/{model_id}/default
POST   /ai/models/{model_id}/test
DELETE /ai/models/{model_id}
```

每条 FastAPI 路由写 `summary`、`description`、`ApiResponse[...]`，删除接口要求 `confirmed: bool`；未确认返回 422。服务商删除前若其模型仍是默认则返回 409，不通过级联删除绕过默认模型约束。

- [ ] **Step 4: 运行配置 API 测试，确认通过**

Run: `cd backend; uv run pytest tests/test_ai_config_api.py -v`，在刚执行凭据片段的同一 shell 中；若换了新 shell，先重跑 Task 2 Step 2 的片段。

Expected: 所有新增 API 测试通过；响应只含统一 `success/data/meta` 契约。

- [ ] **Step 5: 提交配置 API**

```powershell
git add backend/app/ai/schemas.py backend/app/ai/repository.py backend/app/ai/service.py backend/app/ai/router.py backend/app/main.py backend/tests/test_ai_config_api.py
git commit -m "AI：实现模型配置管理接口"
```

### Task 4: 用唯一默认模型替换旧环境网关调用

**Files:**
- Modify: `backend/app/ai/llm/gateway.py`
- Modify: `backend/app/ai/service.py`
- Modify: `backend/app/modules/job/parsing.py`
- Modify: `backend/app/modules/profile/import_router.py`
- Modify: `backend/app/modules/profile/import_service.py`
- Modify: `backend/app/modules/resume/optimization.py`
- Modify: `backend/tests/test_ai_gateway.py`
- Modify: `backend/tests/test_ai_flows.py`
- Modify: `backend/tests/test_profile_import.py`

- [ ] **Step 1: 写失败的网关协议测试**

```python
def test_gateway_posts_openai_compatible_json(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ResolvedAiModel(base_url="https://example.test/v1", remote_model_id="model-x", api_key="secret")
    captured: dict[str, object] = {}
    monkeypatch.setattr(gateway.urllib.request, "build_opener", lambda *_: CapturingOpener(captured))
    asyncio.run(gateway.generate(config, "task", {"field": "value"}, {"type": "object"}))
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["json"]["model"] == "model-x"
    assert captured["headers"]["Authorization"] == "Bearer secret"
```

再覆盖：没有默认模型映射为 409；`base_url` 不合规、HTTP 非本地回环、重定向、超时、非 JSON、超限响应、非 2xx 和响应不含 `choices[0].message.content` 均映射安全错误；无 API Key 时不发送 Authorization；连接测试使用同一请求限制但不发送真实业务数据。

- [ ] **Step 2: 运行网关测试，确认调用签名和行为尚不匹配**

Run: `cd backend; uv run pytest tests/test_ai_gateway.py -v`

Expected: FAIL because `ResolvedAiModel` and新签名尚不存在。

- [ ] **Step 3: 最小化实现默认模型解析和 OpenAI 兼容请求**

在 `service.py` 提供 `resolve_default_model(session, settings) -> ResolvedAiModel`：查询启用的默认模型与启用服务商，解密服务商密文，仅返回内存中的不可变数据；未找到时抛 `ConflictError("尚未配置默认 AI 模型，请先在 AI 模型配置中启用一个模型。")`。

网关新签名为：

```python
async def generate(config: ResolvedAiModel, task: str, input_data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """向默认模型发送一次受限的 OpenAI 兼容结构化请求，不写业务事实。"""
```

请求目标是规范化 `base_url + "/chat/completions"`，body 包含 `model`、一个系统消息（任务名、只返回 JSON）、一个 JSON 用户消息（`input_data` 和 `output_schema`）及 `response_format: {"type": "json_object"}`。限制响应 1 MB、拒绝重定向、超时使用 `ai_timeout_seconds`、不自动重试；仅解析 JSON 字符串 `choices[0].message.content`。

在三个既有入口中遵循同一顺序：读取业务输入 → `await session.rollback()` → 解析默认模型 → `await session.rollback()` → `gateway.generate(...)`。`preview` 接收调用方传入的 `AsyncSession`，导入路由相应传递 session；不得在持有事务时等待 HTTP。

- [ ] **Step 4: 运行网关和 AI 流程测试，确认通过**

Run: `cd backend; uv run pytest tests/test_ai_gateway.py tests/test_ai_flows.py tests/test_profile_import.py -v`

Expected: 网关单测全部通过；未设置隔离库时仅数据库流测试跳过，非数据库测试通过。

- [ ] **Step 5: 提交调用适配**

```powershell
git add backend/app/ai/llm/gateway.py backend/app/ai/service.py backend/app/modules/job/parsing.py backend/app/modules/profile/import_router.py backend/app/modules/profile/import_service.py backend/app/modules/resume/optimization.py backend/tests/test_ai_gateway.py backend/tests/test_ai_flows.py backend/tests/test_profile_import.py
git commit -m "AI：默认模型接入受控调用网关"
```

### Task 5: 实现模型配置页面与导航入口

**Files:**
- Create: `frontend/src/shared/api/ai.ts`
- Create: `frontend/src/shared/api/ai.test.ts`
- Create: `frontend/src/features/ai/AiModelConfigView.vue`
- Create: `frontend/src/features/ai/AiModelConfigView.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/app/NavIcon.vue`

- [ ] **Step 1: 写失败的 API 客户端和页面测试**

```ts
it('新增模型时不把服务商凭据重复提交', async () => {
  await createAiModel('provider-1', { name: '轻量模型', remote_model_id: 'gpt-4.1-mini' })
  expect(requestV1).toHaveBeenCalledWith('/ai/providers/provider-1/models', expect.objectContaining({ init: expect.any(Object) }))
})

it('首个模型读取为默认模型，并显示掩码而非明文', async () => {
  mocked(listAiProviders).mockResolvedValue([providerWithDefaultModel])
  const wrapper = mount(AiModelConfigView)
  await flushPromises()
  expect(wrapper.text()).toContain('默认启用')
  expect(wrapper.text()).toContain('••••alue')
  expect(wrapper.text()).not.toContain('secret-value')
})
```

再覆盖：加载中、空态、加载失败带 request ID、保存忙碌、服务商表单 URL 校验、模型表单、默认切换、测试连接失败、删除弹窗必须确认、窄窗口样式类存在。

- [ ] **Step 2: 运行前端定向测试，确认因文件缺失而失败**

Run: `cd frontend; npm test -- src/shared/api/ai.test.ts src/features/ai/AiModelConfigView.test.ts`

Expected: FAIL with module-not-found.

- [ ] **Step 3: 实现 API 客户端、路由与页面**

`ai.ts` 定义 `AiProvider` 和 `AiModel` 类型，只含后端白名单字段；用 `requestV1` 封装所有 Task 3 端点。路由新增 `{ name: 'ai-models', path: '/ai-models', component: () => import('@/features/ai/AiModelConfigView.vue') }`，`NavIconName` 增加 `'ai'`，导航项显示“AI 模型配置”。

页面遵守现有 `.page-header`、`a-card`、`parseServerError`、`a-spin` 和 `a-alert` 模式：

```vue
<a-popconfirm
  title="删除后将永久移除该服务商的 API Key；此操作不可恢复。"
  ok-text="确认删除"
  cancel-text="取消"
  @confirm="removeProvider(provider)"
>
  <a-button danger :disabled="provider.has_default_model">删除服务商</a-button>
</a-popconfirm>
```

服务商 API Key 输入使用 `type="password"`，编辑时 placeholder 仅显示后端 `api_key_mask`，绝不以 `v-model` 预填真实 Key。模型添加表单只录入名称和远端模型标识；每次写入后调用 `load()`，让默认状态完全以后端为准。

- [ ] **Step 4: 运行定向前端测试，确认通过**

Run: `cd frontend; npm test -- src/shared/api/ai.test.ts src/features/ai/AiModelConfigView.test.ts src/app/router.test.ts`

Expected: 所有定向测试通过。

- [ ] **Step 5: 提交前端页面**

```powershell
git add frontend/src/shared/api/ai.ts frontend/src/shared/api/ai.test.ts frontend/src/features/ai/AiModelConfigView.vue frontend/src/features/ai/AiModelConfigView.test.ts frontend/src/app/router.ts frontend/src/app/router.test.ts frontend/src/app/NavIcon.vue
git commit -m "前端：新增 AI 模型配置页面"
```

### Task 6: 完成文档、全量验证和主线合并准备

**Files:**
- Modify: `backend/.env.example`
- Modify: `docs/ai-gateway.md`
- Modify: `docs/architecture.md`
- Modify: `docs/data-model.md`
- Test: `backend/tests/test_ai_credentials.py`, `backend/tests/test_ai_config_api.py`, `backend/tests/test_ai_gateway.py`, `frontend/src/features/ai/AiModelConfigView.test.ts`

- [ ] **Step 1: 写失败的配置文档/默认模型错误回归测试**

新增一个 API 或流程测试，断言无默认模型时 AI 功能返回 409 且提示用户前往 AI 模型配置，而不是旧的环境变量网关文案。

- [ ] **Step 2: 运行该回归测试，确认旧文案导致失败**

Run: `cd backend; uv run pytest tests/test_ai_gateway.py -k default -v`

Expected: FAIL until Task 4 的错误映射和文档完成。

- [ ] **Step 3: 完成最终配置说明**

在 `backend/.env.example` 仅添加不含真实值的说明：

```dotenv
# TEST/PROD 必填；LOCAL 未设置时仅使用不可用于部署的开发默认值。
JOBARK_AI_CREDENTIAL_ENCRYPTION_KEY=
```

同步数据模型文档中的 `AiProvider 1--N AiModel`、部分唯一默认索引和密文边界。更新 `docs/ai-gateway.md`，移除已废弃的 `JOBARK_AI_GATEWAY_URL/TOKEN` 配置指引；如实现保留兼容字段，标明其移除版本与不得优先于数据库默认模型的规则。

- [ ] **Step 4: 运行全量质量门禁**

Run（本块可独立运行，不依赖前面 shell 是否还活着）：

```powershell
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pyright
# 复用仓库根 .env 的 POSTGRES_* 拼出专用 jobark_test URL；不打印密码，也不指向开发库。
$commonDir = (git rev-parse --path-format=absolute --git-common-dir).Trim()
$repoRoot = Split-Path -Parent $commonDir
$jobarkEnv = @{}
Get-Content (Join-Path $repoRoot '.env') | ForEach-Object { if ($_ -match '^(POSTGRES_(?:USER|PASSWORD|PORT))=(.*)$') { $jobarkEnv[$matches[1]] = $matches[2] } }
if (-not $jobarkEnv['POSTGRES_USER'] -or -not $jobarkEnv['POSTGRES_PASSWORD']) { throw "未在 $repoRoot\.env 找到 POSTGRES_USER/POSTGRES_PASSWORD" }
$port = $jobarkEnv['POSTGRES_PORT']; if (-not $port) { $port = '5432' }
$env:JOBARK_TEST_DATABASE_URL = "postgresql+asyncpg://$($jobarkEnv['POSTGRES_USER']):$($jobarkEnv['POSTGRES_PASSWORD'])@127.0.0.1:$port/jobark_test"
$env:JOBARK_AI_CREDENTIAL_ENCRYPTION_KEY = uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
uv run pytest
cd ..\frontend
npm run lint
npm run typecheck
npm test
npm run build
```

Expected: 每条命令退出码为 0。若隔离数据库不可用，报告为 `verification_pending`，不得把跳过测试称为完整数据库验证。

- [ ] **Step 5: 进行手动界面检查并记录结果**

启动前后端，实际检查桌面宽度与窄窗口：空态、服务商/模型新增、掩码显示、默认切换、测试失败、删除确认和错误编号。确认浏览器网络响应与页面均不含 API Key；如无法启动真实服务，明确标记为未完成的交互验证。

- [ ] **Step 6: 提交文档与验证记录**

```powershell
git add backend/.env.example docs/ai-gateway.md docs/architecture.md docs/data-model.md backend/tests/test_ai_gateway.py
git commit -m "AI：完善模型配置说明与验证"
git status --short
git log --oneline master..HEAD
```

- [ ] **Step 7: 复核并合并回主线**

在工作树执行 `git diff --check master...HEAD`、复读需求验收项并核对每项验证证据。确认无真实凭据、`.env`、生成文件或无关改动后，切回主工作树，执行：

```powershell
git merge --no-ff codex/ai-model-config -m "AI：合并模型配置功能"
```

合并仅在用户已确认的本地主线范围内执行；不推送远端。若任何门禁失败或人工页面检查未做，先报告缺口，不合并。

## 计划自检

- 需求覆盖：多服务商/模型、首条默认、唯一默认、OpenAI 兼容限制、数据库可逆加密、LOCAL 开发默认 key、非 LOCAL 显式 key、掩码 DTO、连接测试、资料发送确认、删除确认、状态/错误和窄窗口均有对应任务。
- 边界覆盖：API Key 归服务商、更新空值保留密文、默认模型不能被直接停用/删除、提供商禁用导致默认失效、禁止非安全 URL、无默认模型安全失败、外部 HTTP 不持有事务、无自动重试和响应体限制均有明确实现或测试步骤。
- 一致性：所有后续调用统一使用 `ResolvedAiModel`，所有前端模型表单统一使用 `remote_model_id`，服务商凭据统一使用 `api_key`/`api_key_mask`/`api_key_configured`。
