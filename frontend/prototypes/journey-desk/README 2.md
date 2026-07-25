# Agent 主控交易台用户旅程原型

独立 Vue/Vite 原型，不进入生产 `/desk`，不修改或伪造服务端事实。它验证：

- 总览、持仓、自选、交易与右侧 Agent 的上下文联动；
- 恰好三条随工作区变化的无卡片快捷指令；
- Agent 通过白名单语义动作导航、选标的和填写未提交草稿；
- 设置、提交、撤单和资金划转被排除；
- 工作流运行态与完成折叠的合同展示，不用浏览器计时伪造进度；
- 提醒 Toast、历史记录和“我的”设置隔离；
- 真实请求 `/api/market/snapshots`，失败时只显示显式错误；
- 「规划」页展示能力缺口矩阵、P0–P8 阶段看板、四条用户旅程与需求纠偏。

## 运行

```bash
cd frontend
npm install
cd prototypes/journey-desk
npm run dev
```

默认地址：`http://127.0.0.1:4320`。`/api` 代理到 `http://127.0.0.1:8000`，
可用 `PROTOTYPE_API_TARGET` 覆盖。

## 验证

```bash
npm run test
npm run type-check
npm run lint
npm run build
```
