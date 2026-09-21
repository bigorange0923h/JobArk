# Frontend

JobArk 前端是位于本目录的独立 npm 工程，工程根即 `frontend/`。

## 技术栈与当前状态

- **已接入**：Vue 3、TypeScript（严格模式）、Vite、Vue Router、API Client、Vitest。
- **已推迟**：Ant Design Vue 与 ECharts。阶段 0 没有任何业务页面，提前安装只会引入未使用的依赖；出现真实页面时再按需接入（见 `docs/architecture.md` 第 4 节）。

## 目录

```
src/
├── main.ts                应用入口
├── App.vue                根组件：最外层布局与路由出口
├── app/
│   ├── router.ts          路由表
│   └── views/             页面：工程状态页、404 兜底页
└── shared/
    └── api/
        ├── types.ts       后端统一契约的 TypeScript 镜像
        ├── client.ts      唯一解包点：成功返回 data，失败抛 ApiError
        ├── system.ts      系统级端点封装（/health）
        └── client.test.ts
```

## 命令

```bash
cd frontend
npm install --include=dev   # 必须带该参数，原因见下方注意事项
npm run dev                 # 开发服务器（:5173），代理 /api 与 /health 到后端
npm run typecheck           # vue-tsc 类型检查
npm test                    # Vitest 单元测试
npm run build               # 类型检查 + 生产构建
```

## 开发期如何访问后端

前端代码**始终使用相对路径**（业务接口经 `requestV1` 自动加 `/api/v1` 前缀），由 Vite 开发服务器代理转发到 `http://127.0.0.1:8000`：

| 前端请求路径 | 代理目标 |
| --- | --- |
| `/api/v1/**` | 后端业务接口 |
| `/health` | 后端健康检查（根路径运维接口，不带版本前缀） |

因此本地开发不涉及跨域，后端 CORS 默认关闭。只有前后端确实分离到不同源时，才通过 `JOBARK_CORS_ALLOWED_ORIGINS` 显式启用白名单。

## 两条环境注意事项

1. **安装依赖必须带 `--include=dev`**。部分 IDE/CI 环境会预设 `NODE_ENV=production`，npm 据此默认 `omit=dev`，导致 `vue-tsc`、`vitest`、`@vitejs/plugin-vue` 等开发依赖被静默跳过，表现为命令找不到或 `npm run typecheck` 报错。也可以先清除 `NODE_ENV` 再安装。
2. **TypeScript 固定在 5.x**。`vue-tsc` 3.x 依赖 `typescript/lib/tsc` 子路径，而 TypeScript 7 已移除该导出（报 `ERR_PACKAGE_PATH_NOT_EXPORTED`）；npm 的 `>=5.0.0` 版本范围拦不住这个不兼容。等 `vue-tsc` 支持 TypeScript 7 后再升级。

## 边界

前端只负责呈现与编辑数据，不拥有领域规则：状态流转、匹配评分、证据校验与自动化权限都在后端执行。所有会引起外部副作用的操作必须以显式确认界面收口。

错误处理约定：`code` 用于分支交互，展示默认使用后端 `message`，不在前端复制文案表；出错时可展示 `ApiError.requestId` 作为"错误编号"。
