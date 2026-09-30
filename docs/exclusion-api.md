# 求职策略排除接口（V1）

所有接口位于 `/api/v1`，沿用统一 `{success,data,meta.request_id}` 响应及统一错误码。当前单人本地产品没有用户、租户或权限字段；写入请求仍须明确确认，422 表示参数不合法、404 表示职位／快照不存在、409 表示乐观锁或输入过期、500 不放行。

| 接口 | 语义 |
| --- | --- |
| `GET /exclusion-policy` | 返回 `version` 和 `rules`；未创建时版本为 0、规则为空。 |
| `PUT /exclusion-policy` | 整体保存 `{version,rules}`；每条规则含稳定 `id`、`kind`、`value`、`enabled`。四类为 `COMPANY_NATURE`、`COMPANY_INDUSTRY`、`COMPANY_NAME`、`JD_KEYWORD`。 |
| `PATCH /jobs/{id}/exclusion-facts` | 提交公司及岗位版本、分类字段和 `confirm:true`；只改明确提交字段。公司性质、行业及岗位安排必须由用户确认，旧行业文本仍保留。 |
| `GET /jobs/{id}/exclusion` | 以当前规则、已确认分类和最新 JD 预览；`decision.verdict` 为 `EXCLUDED`、`REVIEW` 或 `ELIGIBLE`，`reasons` 含规则 ID、维度、依据及可用的原文片段。 |
| `POST /jobs/{id}/exclusion/evaluations` | 为当前投递准备重新评估并保存审计记录；失败不得放行。 |
| `POST /jobs/{id}/exclusion/exception` | 提交快照及规则／公司／岗位版本、原因与 `confirm:true`，登记单职位例外；取消确认不产生写入。 |

`preparation_allowed` 仅表示本组排除规则通过或有当前有效例外，不是匹配合格或外部投递授权。Application 进入 `PREPARING` 或 `READY_TO_APPLY` 时服务端重新评估；手工补记已在外部完成的 `APPLIED` 仍如实记录，不由规则改写历史。未来适配器接入外部提交前，必须以拟提交的 JD 及当前规则调用同一核验，再执行独立的外部提交确认；V1 没有该适配器。

两级行业代码只取显式目录：`TECH`、`FINANCE`、`MANUFACTURING`、`SERVICES` 及接口允许的子级。父级只覆盖目录列出的子级。名称为完整规范化匹配，别名逐条维护；同名不同实体会同时命中。JD 使用字面规则，局部否定或含糊语境进入待核对，不声称覆盖全部自然语言语义。
