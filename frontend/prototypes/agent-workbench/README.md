# Agent 主控交易台隔离原型

该目录是需求与交互验证原型，不进入生产路由，不修改现有前后端。它演示：

- 信息、持仓、自选、交易记录和钱包的桌面工作区；
- 右侧常驻 Agent 随左侧上下文更新三条快捷指令；
- 工作流步骤运行中展开、完成后自动折叠；
- Agent 通过稳定白名单动作切换左侧、选择标的和填充未提交草稿；
- 用户设置、订单提交、撤单、持仓和账本事实不进入 Agent 动作目录；
- 提醒弹窗自动关闭，同时保留可回看的原型记录；
- 行情只请求现有 `/api/market/*` PandaData 后端，失败时不回退到演示价格。

## 运行

先在 `frontend/` 安装主前端依赖，然后运行原型：

```bash
cd frontend
npm install
cd prototypes/agent-workbench
npm run dev
```

默认地址：`http://127.0.0.1:4310`。`/api` 默认代理到
`http://127.0.0.1:8000`，可通过 `PROTOTYPE_API_TARGET` 覆盖。

## 验证

```bash
cd frontend/prototypes/agent-workbench
npm run test
npm run type-check
npm run lint
npm run build
```

原型中的持仓、订单和钱包内容均明确标记为仿真结构数据；不是后端账户事实。生产实现必须
替换为后端 Page View DTO，并保留 T06 用户最终复核。
