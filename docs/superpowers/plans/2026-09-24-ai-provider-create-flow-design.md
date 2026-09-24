# 新增服务商流程与模型字段合并设计

日期：2026-09-24
状态：已与用户逐块确认
关联：`docs/requirements/ai-model-configuration.md`、`docs/adr/0004-ai-model-configuration.md`、`docs/ai-gateway.md`

## 1. 背景与问题

当前 AI 模型配置页（`frontend/src/features/ai/AiModelConfigView.vue`）把"新增服务商表单"与"服务商卡片列表"放在同一页，并且必须先保存服务商，再在其卡片里逐条新增模型。用户提出的四个问题：

1. 页面体验差：新增表单与列表混在一页，没有清晰的"列表 + 新增入口"结构。
2. 新增服务商时不能同时配置其模型，必须保存后回到列表再单独编辑。
3. 一个服务商会有多个模型，创建流程应支持一次提交多个模型配置。
4. 「远端模型标识」这个名称不直观，需要换成通用描述；最新创建的服务商应排在最前。

## 2. 目标与非目标

目标：

- 列表页只负责展示与操作服务商，新增走独立页面。
- 新增服务商时可在同一表单内配置 0..N 个模型，**一次提交、单事务落库**。
- 用户可见的模型字段合并为一个「模型名称」。
- 服务商列表按创建时间倒序，最新创建的在最前。

非目标（本次不做）：

- 不为服务商增加独立详情页（模型管理放在列表展开行）。
- 不改变默认模型规则、乐观锁规则、凭据加解密与掩码边界。
- 不做模型用途分配（按简历优化/职位解析分别指定模型）。
- 不做拖拽排序、批量删除或自定义排序字段。

## 3. 已确认决策

| 决策点 | 结论 |
| --- | --- |
| 新增入口形态 | 独立路由页面 `/ai-models/new` |
| 已有服务商的模型管理 | 列表行展开后管理（保留设置默认、测试连接、编辑、删除、追加） |
| 模型字段 | 合并为一个「模型名称」，写入 `remote_model_id` 与 `name` 同值 |
| 服务商排序 | 后端 `ai_providers` 查询按 `created_at` 倒序 |

## 4. 后端设计

### 4.1 创建服务商（原子）

`POST /api/v1/ai/providers` 请求体新增可选 `models` 数组：

```json
{
  "name": "本地兼容服务",
  "base_url": "https://api.example.com/v1",
  "api_key": "sk-...",
  "description": null,
  "models": [
    { "name": "deepseek-chat", "remote_model_id": "deepseek-chat", "is_enabled": true },
    { "name": "deepseek-reasoner", "remote_model_id": "deepseek-reasoner", "is_enabled": true }
  ]
}
```

- `models` 默认空数组，最多 20 个，超出返回 422（`Field(default_factory=list, max_length=20)`）。
- 每个元素沿用 `ModelCreate` 的字段规则；元素内 `name` 与 `remote_model_id` 由调用方提交同值（见 4.2）。
- 响应仍是 `ProviderRead`（已含 `models`），状态码 201。
- 请求内模型名称重复 → 409，`details[].field = remote_model_id`；服务商名称重复 → 409，`details[].field = name`；地址不安全 → 422。

事务与不变量：

- 服务商与其全部模型在**同一个事务**内写入，任一失败整体回滚，不产生"服务商已建、模型未建"的半成品。
- 默认模型规则沿用现状：全局尚无默认模型时，列表中第一个**启用**的模型自动成为默认；服务商或模型停用则不参与默认候选。
- `models` 为空是合法输入：允许先建服务商、之后在列表展开行补模型。

### 4.2 模型名称合并的写入约定

界面只暴露一个「模型名称」，其值同时写入 `remote_model_id` 与 `name`，两者恒等。

- **不在后端做隐式派生**：请求 DTO 的必填规则不变，避免破坏既有调用方与测试；同值约定由前端在一处完成映射（见 5.4）。
- 代价：已存在的旧数据在下一次编辑时，`name` 会被统一成模型 ID。这是配置记录，不涉及业务事实，不追溯改写其它数据。
- 读取 DTO 不变，继续同时返回 `name` 与 `remote_model_id`。

### 4.3 用户可见文案

- `app/ai/service.py` 中 `_REMOTE_ID_TAKEN` 由"该服务商下已存在相同的远端模型标识。"改为"该服务商下已存在同名的模型。"，避免用户看到界面上已不存在的名词。
- `ModelRead.remote_model_id`、`ModelCreate.remote_model_id`、`ModelUpdate.remote_model_id` 的 `description` 改为"发送给兼容接口的模型名称（与显示名称同值）"。
- 路由 `summary`/`description` 同步（`app/ai/router.py` 中创建服务商与新增模型的接口说明）。

### 4.4 排序

`app/ai/repository.py:list_providers` 的排序由 `AiProvider.created_at` 升序改为**降序**，最新创建的服务商在最前。服务商内部模型仍按 `created_at` 升序，读起来像一份配置清单。

### 4.5 保留的接口

`POST /api/v1/ai/providers/{provider_id}/models` 保持不变，用于给已有服务商追加模型；列表展开行会调用它。其余接口（PATCH、DELETE、设为默认、测试连接）不变。

## 5. 前端设计

### 5.1 列表页 `/ai-models`

`AiModelConfigView.vue` 改写为纯列表页：

- 页头：标题 + 主按钮「新增服务商」（跳 `ai-provider-new`）+「刷新」。
- 主体为 `a-table`：列为 名称（含「已停用」标签）、接口地址、凭据（掩码或"未配置"）、模型（数量，并标出默认模型）、操作（编辑服务商、删除服务商）。
- 删除服务商仍用 Popconfirm 确认，仍在 `has_default_model` 为真时禁用。
- 展开行：该服务商的模型表格（模型名称、状态、设为默认、测试连接、编辑、删除）+ 一行「追加模型」表单，调用既有 `POST /ai/providers/{id}/models`。
- 保留加载态、空态、加载失败态与既有 `data-testid`；不再本地排序，顺序完全以后端为准。
- 保留服务商编辑弹窗（基本信息、凭据掩码提示、启用开关）。

### 5.2 新增页 `/ai-models/new`

新增路由 `{ path: '/ai-models/new', name: 'ai-provider-new', component: () => import('@/features/ai/AiProviderCreateView.vue') }` 与组件 `AiProviderCreateView.vue`：

- 服务商信息区：显示名称、接口地址、API Key（`type="password"`，`autocomplete="off"`）、说明。
- 模型区：可动态增删的行，每行「模型名称」+「启用」开关；初始给 1 个空行；最多 20 行，达上限后「添加模型」按钮禁用。
- 底部：「保存」主按钮 +「取消」返回列表。
- 保存成功 → 跳回列表并显示成功提示；失败 → 就地展示（字段级原因 + `request_id`），输入不清空。
- 前端本地只拦截明显不安全地址与服务商名称为空，完整规则仍以后端 422 为准。

### 5.3 交互状态与文案

- 保存中按钮 loading 并拒绝重复提交；返回/取消在表单有内容时弹确认，避免误丢输入。
- 文案：字段标签统一为「模型名称」，占位文本示例 `如 deepseek-chat`；空态说明改为"尚未配置 AI 服务商"（不变）。
- 窄窗口无页面级横向溢出：表单在 ≤800px 收成单列（沿用现有媒体查询）。

### 5.4 接口封装（`frontend/src/shared/api/ai.ts`）

- 写请求不再暴露 `remote_model_id`：`AiModelCreateInput` 收敛为 `{ name, is_enabled? }`，`AiModelUpdateInput` 去掉 `remote_model_id`，`AiProviderCreateInput` 增加 `models?: AiNewModelInput[]`。
- `ai.ts` 内**唯一一处**把 `name` 映射为 `{ name, remote_model_id: name }`，并注明这是"名称与模型 ID 同值"约定的落点。
- 读取类型 `AiModel` 仍保留 `remote_model_id`（只读展示/镜像用）。

## 6. 校验与边界

前端：模型名称 `trim` 后为空的行直接忽略；同一表单内模型名称重复就地提示、不发请求；行数上限 20。

后端：`models` 上限 20（超出 422）；元素字段长度沿用 `ModelCreate`；重复模型名 409（字段级 details）；单事务回滚。

边界：

- 一个模型都不建、或全部模型停用 → 不会产生默认模型；依赖 AI 的功能仍返回既有 409"尚未配置默认 AI 模型"，行为不变。
- 旧数据 `name` 与模型 ID 不一致时，下次编辑会被统一为模型 ID。
- 并发乐观锁、默认模型不可停用/删除、停用服务商需无默认模型等规则不变。

## 7. 测试

后端（`backend/tests/test_ai_config_api.py`）：

1. 一次创建带多个模型：全部落库、全局仅一个默认、返回的 `name == remote_model_id`。
2. 请求内模型名称重复 → 409 且 `details[].field = remote_model_id`。
3. `models` 超过 20 个 → 422。
4. 服务商列表按创建时间倒序（后创建者在前）。
5. 既有断言重复文案的用例随 4.3 的文案调整同步更新。

前端：

1. `AiModelConfigView.test.ts` 改写：列表顺序、展开行出现模型表与追加表单、点「新增服务商」触发跳转、编辑/删除入口仍在。
2. 新增 `AiProviderCreateView.test.ts`：增删模型行、本地校验、保存只调用一次 `createAiProvider` 且带 `models`、失败保留输入并展示 `request_id`、成功跳回列表。
3. `router.test.ts` 增加 `/ai-models/new` 解析断言。
4. `shared/api/ai.test.ts` 增加 `models` 载荷（含 `remote_model_id` 同值）断言。

验证命令：后端 `uv run ruff check`、`uv run pyright`、`uv run pytest`（设置 `JOBARK_TEST_DATABASE_URL` 跑数据库集成用例）；前端 `npm run lint`、`npm run typecheck`、`npm run test`、`npm run build`。

## 8. 文档同步

- `docs/requirements/ai-model-configuration.md`：把"先建服务商再单独新增模型"改写为"新增服务商时可一次配置多个模型"；字段表述改「模型名称」；补充"服务商列表最新在前"。
- `docs/adr/0004-ai-model-configuration.md` 与 `docs/ai-gateway.md`：措辞与接口清单同步（`POST /ai/providers` 支持 `models`）。
- `docs/superpowers/plans/` 下既有历史计划不回改。

## 9. 影响面与风险

- 前端 `AiModelCreateInput` / `AiModelUpdateInput` 收敛，调用点（列表展开行、编辑弹窗）需同步；编译器与测试会兜住遗漏。
- 后端改动集中在 `app/ai/{schemas/config.py,service.py,repository.py,router.py}`，无数据库迁移。
- 主要风险是"部分成功"：已用单事务消除；前端不做自动重试，避免重复提交。
