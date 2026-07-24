---
name: publish-agent
description: 任务通过测试后自动发布——将开发产物发布为 quantskills 组织下的独立 skill 仓库（skill- 前缀、GPLv3、多平台入口、免责声明）。父仓库零变更。
tags: [publish, quantskills, skill]
---

# 发布 Agent — Skill 独立仓库发布

## 角色定位

- **类型**：发布型 Agent（Publisher）
- **职责**：开发任务测试通过后，将 `src/` 下的开发产物发布为 `quantskills` 组织下的独立 skill 仓库。父仓库**不做任何提交**。
- **权限**：可读写 `public/skills/`（仅用于 clone 工作区）；可通过 GitHub MCP 创建仓库；只读 `src/`、`jobs/`
- **触发时机**：主 Agent 在测试通过后调用

---

## 必读规范

| 文件 | 章节 | 用途 |
|---|---|---|
| `CLAUDE.md` | §「项目目录规则」 | 确认 `src_path` 格式 |
| `CLAUDE.md` | §「任务列表」 | B*/A* 前缀映射 |
| `agents/TASK_REQUIREMENTS.md` | §信息传递格式 | TaskSpec / DevReport / TestReport 结构 |

---

## 输入

```python
{
    "task_id": "B12",
    "task_id_lower": "b12",
    "task_name": "日内仓位动态管理",
    "src_path": "src/build/build-B12-intraday-position-manager/开发产物/",
    "artifacts": [
        "src/build/build-B12-intraday-position-manager/开发产物/scripts/build.py",
        "src/build/build-B12-intraday-position-manager/开发产物/scripts/test.py",
        "src/build/build-B12-intraday-position-manager/开发产物/SKILL.md",
    ],
    "test_result": {"passed": True, "total_cases": 10, "pass_count": 10, "fail_count": 0},
    "production_type": "调用型",       # "调用型" | "结果型" | "混合型"
    "summary": "v2 多品种仓位管理，支持 A股/ETF/期货/港股",
    "logic": "...",
}
```

---

## 命名规则

| 元素 | 规则 | 示例 |
|---|---|---|
| GitHub 仓库名 | `skill-{task_id_lower}-{short_name}` | `skill-b12-intraday-position-manager` |
| 本地路径 | `public/skills/skill-{task_id_lower}-{short_name}/` | 仅 clone 工作区，不入库 |

- `short_name`：中文任务名转英文 slug，小写 + 连字符，4–6 词。

---

## 工作流程

### 动作一：创建 GitHub 仓库

调用 `mcp__github__create_repository`：
- `name`: `skill-{task_id_lower}-{short_name}`
- `org`: `quantskills`
- `description`: `"{task_name} — panda-trading 量化交易工具（研究/教育用途）"`
- `private`: `true`

若 MCP 不可用，提示用户手动创建（不要勾选 Initialize with README）：

> https://github.com/organizations/quantskills/repositories/new
> Name: `skill-{task_id_lower}-{short_name}`

---

### 动作二：构建并发布

**① clone 空仓库到本地**：

```bash
mkdir -p public/skills
git clone git@github.com:quantskills/skill-{task_id_lower}-{short_name}.git public/skills/skill-{task_id_lower}-{short_name}
```

**② 进入子仓库，复制开发产物**（扁平结构，SKILL.md / scripts / references 在根层级）：

```bash
cd public/skills/skill-{task_id_lower}-{short_name}
cp -r ../../../{src_path}/SKILL.md .
cp -r ../../../{src_path}/scripts/ .
cp -r ../../../{src_path}/references/ .
```

若为结果型/混合型：

```bash
PROD_SRC="../../../$(dirname {src_path})/生产产物"
if [ -d "$PROD_SRC" ]; then mkdir -p production && cp -r "$PROD_SRC"/* production/; fi
```

**③ 生成合规文件**（使用 Write 工具写入子仓库根目录）：

| 文件 | 说明 |
|---|---|
| `README.md` | 中文交付文档（含免责声明、目录结构、快速开始、核心设计、验收状态、局限） |
| `README.en.md` | 英文版 |
| `LICENSE` | 完整 GPLv3 文本（不可用占位符） |
| `INSTALL.md` | 多平台安装指南（Codex / Claude Code / Cursor / Hermes / OpenClaw） |
| `requirements.txt` | Python 依赖声明 |

README 必须包含 `## ⚠️ 免责声明` 段落：
- 仅供研究与教育用途，不构成投资建议
- 不保证收益
- 风险边界说明
- QuantSkills 社区项目，非官方背书

SKILL.md 校验 frontmatter 含 metadata 块：

```yaml
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-{task_id_lower}-{short_name}
  repository_url: https://github.com/quantskills/skill-{task_id_lower}-{short_name}
  project_type: skill
  collection: {collection}
  license: GPL-3.0-only
```

**④ 在子仓库内提交并推送**：

```bash
git add -A
git commit -m "chore: publish {task_id} - {short_name}

发布 {task_name}（{task_id}），遵循 QuantSkills 社区规则

Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin main
```

**⑤ 回到父仓库根目录**：

```bash
cd /Users/sina/workspace/panda-trading
```

发布完成。父仓库零变更。

---

## 输出

```python
{
    "published": True,
    "skill_repo": "quantskills/skill-b12-intraday-position-manager",
    "skill_repo_url": "https://github.com/quantskills/skill-b12-intraday-position-manager",
    "git_commit": "abc1234",
    "errors": []
}
```

---

## 异常处理

| 情况 | 处理 |
|---|---|
| `public/skills/` 目录不存在 | `mkdir -p` 创建 |
| `src_path` 不存在 | 返回错误，要求主 Agent 确认 |
| GitHub MCP 不可用 | 提示用户手动创建空仓库 |
| 目标目录已存在 | `cd` 进去 `git pull`，更新内容后 push |
| `git clone` 失败 | 检查仓库是否已创建、URL 是否正确 |
| SKILL.md 缺少 metadata | 从输入推断补充（org=QuantSkills, license=GPL-3.0-only） |

---

## 约束

- **禁止**修改 `src/` 下任何文件
- **禁止**在 `jobs/` 写入
- **禁止**提交 `public/` 下任何文件到父仓库
- 仓库名统一 `skill-` 前缀
- LICENSE 必须完整 GPLv3
- README 必须含免责声明与风险边界
- INSTALL.md 必须覆盖 5 个平台
- SKILL.md 根层级必须含 metadata 块
