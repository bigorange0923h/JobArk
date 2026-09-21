# Frontend

技术栈固定为 Vue 3、TypeScript、Vite、Ant Design Vue 与 ECharts。

- `src/app/`：Vite 启动、路由、全局布局和应用级配置。
- `src/features/`：Dashboard、Jobs、Profile、Resume、Applications 等业务 UI。
- `src/shared/`：Ant Design Vue 的通用封装、ECharts 图表组件、API Client、类型和工具。

业务规则与外部副作用确认由后端负责；前端负责将候选修改、状态变化和确认动作明确呈现给用户。
