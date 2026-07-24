---
name: agent-for-liangshuyuan-tasks
description: 量枢学院多 Agent 协作框架——基于 Claude Code 的量化交易工具开发平台，将任务需求自动分析、路由、开发、测试、发布全流程自动化。内置 6 个专业 Agent，支持 BUILD 工具与 Alpha 因子的 Skill 架构开发。
tags: [agent, multi-agent, quant, framework, panda-trading]
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: agent-for-liangshuyuan-tasks
  repository_url: https://github.com/quantskills/agent-for-liangshuyuan-tasks
  project_type: agent
  collection: agent-framework
  license: MIT
---

```json qsh-form
{
  "version": 1,
  "task": {
    "placeholder": "请描述要开发的量化 BUILD 工具或 Alpha 因子，包括功能、输入输出、验收要求及是否需要发布",
    "required": true
  },
  "prompt_template": "{{#task}}任务与材料：\n{{task}}\n\n{{/task}}{{#attachments}}用户上传的材料（已放入工作区）：\n{{attachments}}\n\n{{/attachments}}请按量枢学院多 Agent 协作流程分析任务类型，依次完成需求结构化、开发、自检、测试与交付；仅在用户明确要求且具备条件时执行发布，并输出中文执行报告。"
}
```

# 量枢学院 · Panda Trading — 多 Agent 协作框架

## 项目定位

- **类型**：Agent 协作框架（Agent Orchestration Framework）
- **解决问题**：将量化交易工具的开发流程标准化——用户只需写需求文件（`jobs/*.txt`），Agent 系统自动完成需求分析 → 路由派发 → 编码开发 → 测试验证 → 社区发布的全流程
- **适用对象**：量化交易开发者、Claude Code 用户、QuantSkills 社区贡献者

## 维护者

- 段绪勇 [https://github.com/duanyong](https://github.com/duanyong)
- 社区维护：QuantSkills 组织

## 适用场景

- 快速开发量化交易 BUILD 工具（仓位管理、止盈止损、监控预警、数据处理等）
- 开发 Alpha 因子与交易信号
- 量化策略的模块化拆分、测试、归档与发布
- 多 Agent 协作开发流水线

## Agent 体系

本项目包含 6 个专业 Agent，按协作流水线组织：

| Agent | 文件 | 职责 |
|---|---|---|
| 主 Agent | `agents/main-agent/SKILL.md` | 调度编排，接收用户指令，串联所有子 Agent |
| 需求分析 Agent | `agents/analyst-agent/SKILL.md` | 读取 `jobs/*.txt`，输出结构化 TaskSpec |
| Build 开发 Agent | `agents/dev-build-agent/SKILL.md` | 开发 B 类任务，使用 panda-builder skill |
| Alpha 开发 Agent | `agents/dev-alpha-agent/SKILL.md` | 开发 A 类任务，实现 Alpha 因子 |
| 测试 Agent | `agents/test-agent/SKILL.md` | 生成测试用例与测试报告，无代码修改权限 |
| 发布 Agent | `agents/publish-agent/SKILL.md` | 将开发产物发布为 quantskills 组织下的独立 skill 仓库 |

### 协作流程

```
jobs/B{编号} {名称}.txt          ← 用户只需写这个
     │
     ▼
┌──────────────────┐
│  需求分析 Agent   │  读取任务文件 → 识别 B/A 类型 → 输出结构化 TaskSpec
└──────┬───────────┘
       │
       ▼
┌─────────────┐
│  主 Agent   │──── B 类 → Build 开发 Agent + panda-builder
└──────┬──────┘──── A 类 → Alpha 开发 Agent
       │
       │ ←── DevReport（产物路径 + 自检报告）
       ▼
┌─────────────┐
│  测试 Agent  │  生成用例 → 运行 → TestReport
└──────┬──────┘
       │ ←── 通过 ✓ / 失败（Bug 回流，最多 3 轮）
       ▼
┌─────────────┐
│  发布 Agent  │  创建 GitHub 仓库（skill- 前缀）→ 构建合规文件 → 推送至 quantskills
└──────┬──────┘
       │
       ▼
   ✅ 任务完成 + 已发布
```

## 任务分类

| 前缀 | 类型 | 开发 Agent | 产出目录 |
|---|---|---|---|
| `B` | BUILD 工具 | Build 开发 Agent | `src/build/build-{编号}-{名称}/` |
| `A` | Alpha 因子 | Alpha 开发 Agent | `src/alpha/alpha-{编号}-{名称}/` |

## 项目结构

```
panda-trading/
├── AGENTS.md                       ← 本文件（Agent 声明）
├── README.md                       ← 中文项目说明
├── README.en.md                    ← 英文项目说明
├── LICENSE                         ← MIT License
├── CLAUDE.md                       ← Claude Code 项目规范
│
├── agents/                         ← 多 Agent 协作规范
│   ├── TASK_REQUIREMENTS.md        ←   Agent 分工、流程、信息传递格式
│   ├── main-agent/SKILL.md         ←   主 Agent 调度规则
│   ├── analyst-agent/SKILL.md      ←   需求分析 Agent 规则
│   ├── dev-build-agent/SKILL.md    ←   Build 开发 Agent 规则
│   ├── dev-alpha-agent/SKILL.md    ←   Alpha 开发 Agent 规则
│   ├── test-agent/SKILL.md         ←   测试 Agent 规则
│   └── publish-agent/SKILL.md      ←   发布 Agent 规则（遵循 QuantSkills 社区规则）
│
├── skills/                         ← 项目本地 Skill
│   └── panda-builder/              ←   BUILD 脚手架与验收规范
│
├── docs/                           ← 生产规则文档
│   ├── BUILD开发与生产规则V2.md
│   └── Alpha因子开发与生产规则V2.md
│
├── jobs/                           ← 原始任务需求
│
├── src/                            ← 开发产物（所有产出必须放此处）
│   ├── build/                      ←   BUILD 工具产出
│   └── alpha/                      ←   Alpha 因子产出（预留）
│
└── public/                         ← 发布工作区（gitignored，不入库）
```

## 环境要求

- Python 3.8+
- 零第三方依赖（每个 Skill 默认使用纯标准库）
- Claude Code CLI
- GitHub MCP（用于发布 Agent 自动创建仓库）
- `GITHUB_TOKEN` 环境变量

## 已知限制

1. **仅支持 Claude Code 运行时**：Agent 协作流程依赖 Claude Code 的多 Agent 能力，尚未适配其他 AI 编码助手
2. **单任务串行**：当前一次只处理一个任务，不支持并行任务队列
3. **无 CI/CD 集成**：发布流程需要手动触发或在 Claude Code 交互中完成
4. **GitHub 依赖**：发布 Agent 依赖 GitHub MCP，Gitee 仅作为镜像备份
5. **仅中文任务文件**：`jobs/*.txt` 当前仅支持中文需求描述
6. **无回滚机制**：发布后的 Skill 若发现问题需手动修复和重新发布
