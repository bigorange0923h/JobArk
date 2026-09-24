# 新增服务商流程与模型字段合并实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 AI 服务商的新增与模型配置一次完成（列表页 + 独立新增页 + 展开行管理模型），并把模型字段合并为一个「模型名称」。

**Architecture:** 后端在 `POST /api/v1/ai/providers` 上接受可选 `models` 数组，服务商与全部模型在同一事务内落库；前端 `ai.ts` 在唯一一处把「模型名称」映射为 `{ name, remote_model_id }` 同值；列表页只读且倒序展示，新增页负责一次提交。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Alembic + Pytest；Vue 3 + TypeScript + Ant Design Vue + Vitest。

设计依据：`docs/superpowers/plans/2026-09-24-ai-provider-create-flow-design.md`。

**验证环境：**

- 后端：`cd backend`，数据库集成测试需 `JOBARK_TEST_DATABASE_URL=postgresql+asyncpg://jobark_app:jobark_123456@127.0.0.1:5432/jobark_test`。
- 前端：`cd frontend`。

---

## Task 1: 后端文案与列表排序

**Files:**
- Modify: `backend/app/ai/repository.py`（`list_providers` 排序）
- Modify: `backend/app/ai/service.py`（`_REMOTE_ID_TAKEN` 文案）
- Modify: `backend/app/ai/schemas/config.py`（`remote_model_id` 字段说明）
- Test: `backend/tests/test_ai_config_api.py`

**Step 1: 写失败测试**

在 `backend/tests/test_ai_config_api.py` 末尾追加：

```python
def test_providers_are_listed_newest_first(db_client: TestClient) -> None:
    """服务商列表按创建时间倒序：最新创建的在最前，便于刚配置完就能看到。"""
    first = _create_provider(db_client, name="先创建的服务", base_url="https://first.test/v1")
    second = _create_provider(db_client, name="后创建的服务", base_url="https://second.test/v1")

    listed = db_client.get(f"{API}/providers").json()["data"]
    assert [item["id"] for item in listed] == [second["id"], first["id"]]
```

**Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_ai_config_api.py::test_providers_are_listed_newest_first -q`
Expected: FAIL（顺序为先创建者在前）

**Step 3: 改实现**

- `repository.list_providers`：`order_by(AiProvider.created_at.desc())`，并更新 docstring 为"最新创建的在前"。
- `service._REMOTE_ID_TAKEN`：改为 `"该服务商下已存在同名的模型。"`。
- `schemas/config.py`：`ModelRead.remote_model_id`、`ModelCreate.remote_model_id`、`ModelUpdate.remote_model_id` 的 `description` 改为"发送给兼容接口的模型名称，与显示名称同值"。

**Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_ai_config_api.py -q`
Expected: PASS（21 passed）

**Step 5: 提交**

```bash
git add backend/app/ai/repository.py backend/app/ai/service.py backend/app/ai/schemas/config.py backend/tests/test_ai_config_api.py
git commit -m "AI：服务商列表倒序并统一模型名称文案"
```

---

## Task 2: 后端创建服务商支持 `models` 数组

**Files:**
- Modify: `backend/app/ai/schemas/config.py`（`ProviderCreate.models`）
- Modify: `backend/app/ai/service.py`（`create_provider` 单事务写入多个模型）
- Modify: `backend/app/ai/router.py`（接口 `description`）
- Test: `backend/tests/test_ai_config_api.py`

**Step 1: 写失败测试**

```python
def _create_provider_with_models(client: TestClient) -> dict[str, Any]:
    """一次提交两个模型的服务商创建请求；供多个用例复用。"""
    return _create_provider(
        client,
        name="批量配置服务",
        base_url="https://batch.test/v1",
        models=[
            {"name": "qwen3", "remote_model_id": "qwen3", "is_enabled": True},
            {"name": "gpt-4.1-mini", "remote_model_id": "gpt-4.1-mini", "is_enabled": True},
        ],
    )


def test_create_provider_with_models_in_one_request(db_client: TestClient) -> None:
    """一次创建可同时提交多个模型，且全局只产生一个默认模型。"""
    provider = _create_provider_with_models(db_client)

    assert [model["remote_model_id"] for model in provider["models"]] == ["qwen3", "gpt-4.1-mini"]
    assert all(model["name"] == model["remote_model_id"] for model in provider["models"])

    models = _all_models(db_client)
    assert sum(1 for model in models if model["is_default"]) == 1
    assert next(model for model in models if model["remote_model_id"] == "qwen3")["is_default"] is True


def test_create_provider_with_duplicate_models_rolls_back_everything(db_client: TestClient) -> None:
    """请求内的模型名称重复返回 409，且整体回滚，不留下半成品。"""
    response = db_client.post(
        f"{API}/providers",
        json={
            "name": "重复模型服务",
            "base_url": "https://duplicate.test/v1",
            "models": [
                {"name": "qwen3", "remote_model_id": "qwen3"},
                {"name": "qwen3", "remote_model_id": "qwen3"},
            ],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"][0]["field"] == "remote_model_id"
    assert db_client.get(f"{API}/providers").json()["data"] == []


def test_create_provider_rejects_too_many_models(db_client: TestClient) -> None:
    """模型数量超过上限返回 422，而不是写入一半。"""
    models = [{"name": f"model-{index}", "remote_model_id": f"model-{index}"} for index in range(21)]
    response = db_client.post(
        f"{API}/providers",
        json={"name": "超量服务", "base_url": "https://many.test/v1", "models": models},
    )
    assert response.status_code == 422, response.text
    assert db_client.get(f"{API}/providers").json()["data"] == []
```

**Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_ai_config_api.py -k "create_provider_with" -q`
Expected: FAIL（`models` 为未知字段，422）

**Step 3: 改实现**

- `ProviderCreate` 增加：`models: list[ModelCreate] = Field(default_factory=list, max_length=20, description="随服务商一并创建、一次提交的模型；最多 20 个。")`
- `service.create_provider`：在 `repo.add(session, provider)` 之后按顺序创建模型（`provider.id` 由应用侧 `uuid4` 生成，无需额外 flush 取 id），默认标记规则与 `create_model` 一致（全局无默认时的第一个启用模型成为默认），最后统一 `commit`。
- 新增私有辅助函数 `_first_duplicate_remote_id(models: Sequence[ModelCreate]) -> str | None`，用于请求内重复校验。
- 冲突文案复用 `_REMOTE_ID_TAKEN`，`details[].field = "remote_model_id"`。
- 提交后 `session.refresh(provider)` 并逐个 `refresh` 新建模型，确保读取 DTO 拿到 `created_at`/`version` 等服务端默认值。
- `router.create_provider` 的 `description` 补充"可同时提交 `models`，服务商与模型在同一事务内落库，任一失败整体回滚"。

**Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_ai_config_api.py -q`
Expected: PASS（24 passed）

**Step 5: 提交**

```bash
git add backend/app/ai/schemas/config.py backend/app/ai/service.py backend/app/ai/router.py backend/tests/test_ai_config_api.py
git commit -m "AI：创建服务商支持同时提交多个模型"
```

---

## Task 3: 前端 API 层收敛为「模型名称」

**Files:**
- Modify: `frontend/src/shared/api/ai.ts`
- Test: `frontend/src/shared/api/ai.test.ts`

**Step 1: 写失败测试**

把 `ai.test.ts` 中"新增模型"与"更新模型"两条用例改为：

```ts
it('新增模型只提交名称，模型 ID 与名称同值由本层补齐', async () => {
  await createAiModel('provider-1', { name: 'gpt-4.1-mini' })

  expect(lastRequest().path).toBe('/ai/providers/provider-1/models')
  expect(lastBody()).toEqual({ name: 'gpt-4.1-mini', remote_model_id: 'gpt-4.1-mini' })
})

it('新增服务商可携带多个模型，元素同样补齐模型 ID', async () => {
  await createAiProvider({
    name: '本地兼容服务',
    base_url: 'http://localhost:11434/v1',
    models: [{ name: 'qwen3' }, { name: 'qwen2.5', is_enabled: false }],
  })

  expect(lastBody()).toEqual({
    name: '本地兼容服务',
    base_url: 'http://localhost:11434/v1',
    models: [
      { name: 'qwen3', remote_model_id: 'qwen3' },
      { name: 'qwen2.5', remote_model_id: 'qwen2.5', is_enabled: false },
    ],
  })
})

it('更新模型使用 PATCH 且不重复提交模型 ID', async () => {
  await updateAiModel('model-1', { version: 3, name: 'qwen3-max' })

  expect(lastRequest().path).toBe('/ai/models/model-1')
  expect(lastBody()).toEqual({ version: 3, name: 'qwen3-max', remote_model_id: 'qwen3-max' })
})
```

**Step 2: 运行测试确认失败**

Run: `npm run test -- src/shared/api/ai.test.ts`
Expected: FAIL（`remote_model_id` 缺失 / 类型不匹配）

**Step 3: 改实现（`ai.ts`）**

- `AiModelCreateInput` → `{ name: string; is_enabled?: boolean }`；`AiModelUpdateInput` 去掉 `remote_model_id`。
- 新增 `AiProviderCreateInput.models?: AiModelCreateInput[]`。
- 新增私有 `toModelPayload(input)`：返回 `{ name, remote_model_id: name, ...(is_enabled === undefined ? {} : { is_enabled }) }`，并注明这是"名称与模型 ID 同值"约定的唯一落点。
- `createAiProvider` 在提交前把 `models` 映射为 `toModelPayload` 结果；未传 `models` 时不带该字段。
- 读取类型 `AiModel.remote_model_id` 保留（只读展示）。

**Step 4: 运行测试确认通过**

Run: `npm run test -- src/shared/api/ai.test.ts`
Expected: PASS

**Step 5: 提交**

```bash
git add frontend/src/shared/api/ai.ts frontend/src/shared/api/ai.test.ts
git commit -m "前端：模型写请求收敛为单一模型名称"
```

---

## Task 4: 前端列表页改写

**Files:**
- Modify: `frontend/src/features/ai/AiModelConfigView.vue`
- Test: `frontend/src/features/ai/AiModelConfigView.test.ts`

**结构要求：**

- 页头：标题、「新增服务商」按钮（`data-testid="create-provider-link"`，点击 `router.push({ name: 'ai-provider-new' })`）、「刷新」。
- `a-table` 服务商列表，不本地排序；列为 名称 +「已停用」标签、接口地址、凭据（掩码 / 未配置）、模型数量（标出默认模型名）、操作（编辑 / 删除）。
- `#expandedRowRender`：该服务商模型表格（`data-testid="models-<providerId>"`）+ 追加模型表单（模型名称输入 +「追加模型」按钮，`create-model-<providerId>`）。
- 保留：加载态 `loading`、空态 `empty`、加载失败 `load-error`、操作错误 `form-error`、成功提示 `action-notice`；服务商编辑弹窗、模型编辑弹窗及其 testid 不变。
- 删除服务商与删除模型的确认弹窗、`has_default_model` 时的禁用规则不变。

**测试要求：** 保留既有用例（调整 testid 与文案），新增："点击「新增服务商」跳转到 `ai-provider-new`"、"展开行内追加模型只提交名称"、"列表顺序完全按接口返回（不本地排序）"。测试需 `vi.mock('vue-router')` 提供 `useRouter`。

**验证：** `npm run typecheck`、`npm run test -- src/features/ai/AiModelConfigView.test.ts`。

**提交：**

```bash
git add frontend/src/features/ai/AiModelConfigView.vue frontend/src/features/ai/AiModelConfigView.test.ts
git commit -m "前端：AI 服务商列表改为展开行管理模型"
```

---

## Task 5: 前端新增页与路由

**Files:**
- Create: `frontend/src/features/ai/AiProviderCreateView.vue`
- Create: `frontend/src/features/ai/AiProviderCreateView.test.ts`
- Modify: `frontend/src/app/router.ts`
- Test: `frontend/src/app/router.test.ts`

**结构要求：**

- 服务商信息区：显示名称、接口地址、API Key（`type="password"`，`autocomplete="off"`）、说明。
- 模型区：动态行（模型名称 + 启用开关），初始 1 行；「添加模型」在 20 行时禁用；每行可删除。
- 本地校验：服务商名称与接口地址非空、地址安全（复用 `isSafeBaseUrl` 逻辑）；`trim` 后为空的模型行忽略；同一表单内模型名称重复就地提示且不发请求。
- 保存：只调用一次 `createAiProvider`，成功跳回 `ai-models` 并提示；失败就地展示（含 `request_id`）并保留输入；保存中拒绝重复提交。
- testid：`provider-name`、`provider-base-url`、`provider-api-key`、`provider-description`、`model-name-0`、`model-enabled-0`、`add-model`、`remove-model-0`、`submit-provider`、`cancel`、`form-error`。

**路由：** 在 `/ai-models` 之后加 `{ path: '/ai-models/new', name: 'ai-provider-new', component: () => import('@/features/ai/AiProviderCreateView.vue') }`；`router.test.ts` 增加解析断言。

**验证：** `npm run typecheck`、`npm run test -- src/features/ai/AiProviderCreateView.test.ts src/app/router.test.ts`。

**提交：**

```bash
git add frontend/src/features/ai/AiProviderCreateView.vue frontend/src/features/ai/AiProviderCreateView.test.ts frontend/src/app/router.ts frontend/src/app/router.test.ts
git commit -m "前端：新增 AI 服务商独立页面支持多模型"
```

---

## Task 6: 文档同步与全量验证

**Files:**
- Modify: `docs/requirements/ai-model-configuration.md`
- Modify: `docs/adr/0004-ai-model-configuration.md`
- Modify: `docs/ai-gateway.md`

**内容：** 需求文档改写"新增服务商时可一次配置多个模型"、字段表述改「模型名称」、补充列表倒序；ADR 与 AI 网关文档同步接口清单与措辞。

**全量验证命令：**

```bash
cd backend && uv run ruff check && uv run pyright && uv run pytest -q
cd frontend && npm run lint && npm run typecheck && npm run test && npm run build
```

**提交：**

```bash
git add docs/requirements/ai-model-configuration.md docs/adr/0004-ai-model-configuration.md docs/ai-gateway.md
git commit -m "文档：同步新增服务商流程与模型名称约定"
```
