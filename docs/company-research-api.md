# 独立公司搜索协议与边界

默认未配置。`JOBARK_COMPANY_SEARCH_URL` 须由使用者提供实现本文协议的受信任 HTTPS 服务；没有绑定任何付费供应商，也没有开启普通聊天模型的原生搜索。配置不等于真实验收。

请求为 POST JSON：`identity` 仅法人、官网、城市、招聘主体，`query` 为固定公开资料维度，`limit` 最大 8。可配置令牌作为 Authorization Bearer，不进日志或响应。响应严格为 `{"sources":[{"url":"https://...","title":"...","excerpt":"必要摘录","published_at":null}],"partial":false}`。每轮最多 8 来源；总计最多 6 查询、8 去重来源，单请求 15 秒，全部外部步骤 90 秒，不自动重试。

搜索端点校验 DNS 公网地址并固定连接 IP，TLS 仍验证原域名，禁代理与重定向，响应上限 1MB。来源仅作为公开 HTTPS 链接/摘录保留，不获取任意网页正文；因此不执行网页指令、不绕过登录/验证码/付费墙。来源链接并不证明该网页真实可用或内容已独立核实。

`GET /api/v1/company-research/capabilities` 告知配置、服务商和外发范围。`POST /api/v1/jobs/{id}/company-research` 接受 `entity_confirmed`、`confirm_external`、公司乐观锁版本及明确实体字段；缺资源404，身份未确认保存 WAITING_USER，缺联网确认422，公司版本/确定排除409。搜索或总结未成功保存独立报告的明确状态，HTTP 成功表示该报告记录已保存，不能理解为联网分析整体成功。`GET` 同路径读取历史，不联网。

公司报告 immutable，来源必要摘录、哈希、URL、标题、绑定依据、查询时间与可空发布时间保存在 report_json，不自动更新 Company 分类。完成报告可复用24小时，显示年龄；未配置/失败不缓存成完成。来源不充分、转载、主体歧义或矛盾保留未知，普通网页只能线索/观点。模型结论按五维保存事实/推测/观点/未知，校验逐字出处；不做公司总评级，不计能力分。未来按真实搜索服务适配时需先验证协议、条款与真实来源，不假定这轮替身证明联网可用。

能力接口同时返回可空的 `model_service`、`model_name`。联网确认提交 `expected_service`、`expected_model`，总结前重新核对实际默认配置；未配置或配置变化时不向未确认模型发送来源，保存 PARTIAL 与 SUMMARY_UNAVAILABLE。搜索来源仍可独立读取，确认记录保留本次模型目标。
