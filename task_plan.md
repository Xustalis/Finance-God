# Finance-God 用户画像入口实施计划

## 目标
删除旧产品链路，交付 Vue 用户画像入口、FastAPI 画像/AI/管理 API、原创导师视觉资产和工作台交接协议。

## 阶段
- [complete] 1. 后端合同、模型、规则、RBAC 与测试
- [complete] 2. Vue 前端、响应式引导流程与语音降级
- [complete] 3. 原创导师图像资产与视觉整合
- [complete] 4. OpenAPI、数据库重建脚本和接入文档
- [complete] 5. 全量测试、浏览器验收和最终审查
- [in_progress] 6. 冗余文件、依赖、构建产物和死代码审计
- [pending] 7. 白盒代码质量、合同、权限、并发与异常路径复审
- [pending] 8. 黑盒注册/登录/引导/报告/管理端/工作台全流程测试
- [pending] 9. UI 视觉、响应式、触控、键盘与无障碍全面核查
- [pending] 10. 修复已确认问题、删除已证明冗余项并完成回归门禁
- [complete] 11. 独立管理端、DeepSeek 与自动画像需求澄清及设计规格
- [pending] 12. 规格复核后制定实施计划并按 TDD 落地

## 已锁定决策
- 旧 React 前端与无关后端模块全部删除。
- 开发数据库允许重建，不迁移旧业务数据。
- 用户必须先登录；角色为 user/admin。
- AI 对话 6-12 轮，同一维度最多追问 2 次，敏感问题可拒答。
- 方向只包含五类资产方向，不输出具体基金或交易。
- 工作台通过 API 保存 + 限定 origin 的 postMessage 接入。

## 错误记录
| 错误 | 尝试 | 处理 |
|---|---:|---|
| imagegen 技能初始路径错误 | 1 | 改用 `.system/imagegen/SKILL.md` |
| 尝试读取不存在的 `backend/app/schemas/auth.py` | 1 | 认证 schema 实际内联在 `backend/app/api/v1/auth.py`，后续使用该文件 |
| 沙箱禁止读取进程列表 `ps` | 1 | 不再依赖进程检查，改用 agent 状态和工作树变更判断进度 |
| 前端修复代理模型连接中断 | 1 | 已确认 RED 测试落盘，从缺少 `bootstrap.ts` 的断点续跑 |
| `sips` 无法解析导师 SVG | 1 | 改用本机 Chrome 无头渲染后以 `cwebp` 编码 |
| Playwright wrapper 无执行权限 | 1 | 改用 `bash` 调用；最终资产渲染使用已安装 Chrome |
| Chrome 路径首次未加引号 | 1 | 对含空格的应用路径加引号后成功执行 |
| 导师引用补丁上下文已变化 | 1 | 重新读取文件顶部并按最新内容应用窄补丁 |
| Playwright 首次打开管理路由创建了新浏览器上下文 | 1 | 重新登录验收用户，确认角色守卫重定向到 `/app/exe?notice=admin_required` |
| Playwright `run-code` 首次传入语句而非函数 | 1 | 按 CLI 合同改为 `async (page) => { ... }` 函数 |
| 本机缺少 PostgreSQL `dropdb` 客户端 | 1 | 安全脚本已先校验目标库；改用 Compose 数据库容器内客户端仅重建 `finance_god` |

## 阶段验收记录
- 后端规格复审通过；质量复审通过。
- 后端全量测试：57 passed, 1 skipped。
- 本地 PostgreSQL 位于 Alembic head，`alembic check` 无漂移。
- 前端全量测试：36/36；`vue-tsc --noEmit` 与生产构建通过。
- 动态问题由服务端 `current_question` 唯一驱动，刷新恢复、确认/拒绝分支和 6-12 轮边界均通过测试。
- Playwright 已完成注册、10 步客观信息、动态对话、刷新恢复、画像报告、五类方向、方向保存和普通用户管理路由守卫的真实闭环。
- 375、768、1024 横屏和 1440 宽度完成响应式检查；最终质量复审 `APPROVED`。

## 本轮全面核查标准
- 冗余项必须同时满足：运行时、构建、测试、文档和部署均无引用；删除后全量门禁保持通过。
- 白盒覆盖 API 合同、状态机、幂等、RBAC、资源归属、并发/事务、AI 失败和未成年分支。
- 黑盒覆盖首次用户、恢复用户、拒答、语音降级、模型异常、报告方向选择和管理权限。
- UI 对照金融信任型设计基线，检查 320-1440px、横屏、键盘、焦点、对比度、44px 触控和 reduced-motion。
