# Finance-God 文档中心

> 文档类型：参考 / Reference
>
> 目标读者：产品、设计、前后端研发、测试与维护者
>
> 维护原则：代码和可复现测试描述当前实现；PRD 描述目标与验收；历史材料只解释决策来源。

## 1. 从这里开始

| 需要了解 | 首选文档 |
| --- | --- |
| 安装、配置与运行 | [`../README.md`](../README.md) |
| 仓库结构、路由、API 和测试入口 | [`项目索引.md`](项目索引.md) |
| 产品范围与业务验收 | [`prd/Finance-God_MVP_PRD_v1.0.md`](prd/Finance-God_MVP_PRD_v1.0.md) |
| 交易域需求 | [`prd/Finance-God_交易台_PRD_v1.0.md`](prd/Finance-God_交易台_PRD_v1.0.md) |
| 前端强制规范 | [`page-design/01_前端统一设计规范.md`](page-design/01_前端统一设计规范.md) |
| 前后端职责与数据合同 | [`page-design/02_前后端职责与数据合同.md`](page-design/02_前后端职责与数据合同.md) |
| 前端设计入口 | [`page-design/00_前端设计文档索引.md`](page-design/00_前端设计文档索引.md) |
| 后端架构 | [`../backend/docs/architecture-overview.md`](../backend/docs/architecture-overview.md) |
| Finance API | [`../backend/docs/finance-api-reference.md`](../backend/docs/finance-api-reference.md) |

## 2. 文档层级

### 2.1 现行文档

现行文档用于开发、评审和验收。发生冲突时按以下顺序处理：

1. 安全、数据完整性和运行时事实；
2. 交易域 PRD 与前端强制规范；
3. 页面专项规格；
4. 研究、早期方案和实施计划。

文档与代码不一致时，不应直接把代码行为写回 PRD。先判断差异属于实现缺陷、未完成能力，
还是需求已经变更，再更新对应的唯一信息源。

### 2.2 参考资料

- `research/`：竞品、产品形态和原型研究；
- `market-analysis/`：市场与商业分析；
- `architecture/`、`experiments/`：Agent 架构与实验约定；
- `research/frontend/`：布局裁决和开源项目调研依据。

参考资料不能单独扩大当前版本范围，也不能作为功能已经交付的证据。

### 2.3 历史记录

- `specs/`：早期产品方案；
- `superpowers/plans/`、`superpowers/specs/`：带日期的设计与实施记录。

历史记录按原始上下文保留，不持续追随代码更新。需要恢复其中方案时，应重新立项并以现行
PRD、规范和安全约束复核。

## 3. 维护规则

- 新文档必须说明文档类型、目标读者、用途或状态；
- 同一规则只保留一个权威位置，其他文档使用链接引用；
- 一次性验收结果应附带日期和代码版本，不作为永久规范；
- 删除或重命名文档时，同一变更中清理所有 Markdown 引用；
- 代码入口、路由、API、迁移或测试命令变化时更新 `项目索引.md`；
- 前端任务必须先阅读前端强制规范、验收模板和受影响路由的页面规格。
