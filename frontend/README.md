# Frontend

JobArk 前端是位于本目录的独立 npm 工程，工程根即 `frontend/`。

## 技术栈与当前状态

- **已接入**：Vue 3、TypeScript（严格模式）、Vite、Vue Router、Ant Design Vue（按需自动导入）、API Client、Vitest。
- **已推迟**：ECharts。仪表盘出现时再接入，当前没有图表页面。
- **已实现的页面**：个人资料（`features/profile/`，覆盖档案根信息、证据、技能、经历、项目、教育、语言、求职偏好与资料修订）。

## 目录

```
src/
├── main.ts                应用入口
├── App.vue                根组件：最外层布局与路由出口
├── test-setup.ts          组件测试的 DOM 环境补丁（jsdom 缺 matchMedia/ResizeObserver）
├── app/
│   ├── router.ts          路由表
│   └── views/             跨领域壳页面：工程状态页、404 兜底页
├── features/
│   └── profile/
│       ├── ProfileView.vue        页面容器：加载/失败/未创建/就绪四种状态与冲突处理
│       ├── descriptors.ts         六类事实的字段、表格列与写操作（表单的单一来源）
│       ├── types.ts               描述符类型
│       └── components/            通用事实面板、档案根信息、偏好、修订面板
└── shared/
    ├── api/
    │   ├── types.ts       后端统一契约的 TypeScript 镜像
    │   ├── client.ts      唯一解包点：成功返回 data，失败抛 ApiError
    │   ├── profile.ts     Profile 领域的类型与调用（后端 schema 的手工镜像）
    │   └── system.ts      系统级端点封装（/health）
    └── forms/
        └── serverErrors.ts  把失败响应解析成"总体提示 / 字段级原因 / 请求标识"
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

## 三条环境注意事项

1. **安装依赖必须带 `--include=dev`**。部分 IDE/CI 环境会预设 `NODE_ENV=production`，npm 据此默认 `omit=dev`，导致 `vue-tsc`、`vitest`、`@vitejs/plugin-vue` 等开发依赖被静默跳过，表现为命令找不到或 `npm run typecheck` 报错。也可以先清除 `NODE_ENV` 再安装。
2. **TypeScript 固定在 5.x**。`vue-tsc` 3.x 依赖 `typescript/lib/tsc` 子路径，而 TypeScript 7 已移除该导出（报 `ERR_PACKAGE_PATH_NOT_EXPORTED`）；npm 的 `>=5.0.0` 版本范围拦不住这个不兼容。等 `vue-tsc` 支持 TypeScript 7 后再升级。
3. **`components.d.ts` 必须提交**。Ant Design Vue 的组件由 `unplugin-vue-components` 在构建时自动导入并生成该声明文件；`npm run build` 的执行顺序是 `vue-tsc` 在前、`vite` 在后，因此干净环境里若没有它，类型检查会先失败。它是生成物，但属于构建所需的输入，不放进 `.gitignore`。

## 测试的环境约定

默认环境是 `node`（传输层测试只需替换 `fetch`）。**组件测试必须在文件顶部标注 `@vitest-environment jsdom`**：不要全局改成 jsdom，因为 jsdom 没有完整实现 `AbortSignal.timeout`，会让传输层的超时测试在一个与被测逻辑无关的地方失败。

`src/test-setup.ts` 为 jsdom 补上 `matchMedia` 与 `ResizeObserver`——AntDV 的栅格与部分组件挂载时会调用它们，缺失时组件直接抛错，而不是"渲染得不一样"。

## 边界

前端只负责呈现与编辑数据，不拥有领域规则：状态流转、匹配评分、证据校验与自动化权限都在后端执行。所有会引起外部副作用的操作必须以显式确认界面收口。

错误处理约定：`code` 用于分支交互，展示默认使用后端 `message`，不在前端复制文案表；出错时可展示 `ApiError.requestId` 作为"错误编号"。
