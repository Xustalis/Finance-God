# Agent 主控交易台隔离原型

该目录是需求与交互验证原型，不进入生产路由，不修改现有前后端。它演示：

- 信息、持仓、自选、交易、记录和钱包六个一级桌面工作区；交易内保留仿真订单草稿与策略工具；
- 右侧常驻 Agent 随左侧上下文更新三条快捷指令；窗口小于 1024 px 时保留当前交易台并默认收为可见轨道；
- 头部导航显示当前“交易台”，提醒 Toast、提醒历史和用户设置弹层均锚定头部入口；
- 左右默认 1:1 对称，中间使用报纸装订折线；左栏任务页与右栏对话/任务页分别切换并采用相反方向的撕纸过渡；
- 工作流步骤运行中展开、完成后自动折叠；
- Agent 通过稳定白名单动作切换左侧、选择标的和填充未提交草稿；
- Agent 侧栏可主动收起，偏好可保存；恢复默认布局时回到对称双栏；
- 用户设置、订单提交、撤单、持仓和账本事实不进入 Agent 动作目录；
- 信息提醒自动关闭，较高等级提醒保持到主动关闭，同时保留可回看的原型记录；
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
替换为后端 `DeskBootstrapView`，并保留用户最终复核。
