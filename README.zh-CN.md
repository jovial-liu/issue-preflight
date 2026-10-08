# Issue Preflight

**让 AI 开始修 GitHub issue 前，先核对贡献证据。**

[English](README.md)

“issue 还开着”不代表没人修。已有 PR 可能被自动关闭，贡献规则也可能要求认领、人工复核或提前讨论。Issue Preflight 汇总这些证据，生成带来源链接的 Markdown / JSON 报告，供你和代码 Agent 做开工判断。

本地运行，使用已有 `gh` 登录，Python 运行时零第三方依赖，不需要模型 API Key。GitHub 请求均为 GET，不会自动留言、认领、建分支或提交 PR。

## 安装与使用

需要 Python 3.10+ 和 [GitHub CLI](https://cli.github.com/)。下面第一种方式还需要 [pipx](https://pipx.pypa.io/stable/installation/)。

```bash
gh auth login
pipx install https://github.com/jovial-liu/issue-preflight/releases/download/v0.1.1/issue_preflight-0.1.1-py3-none-any.whl
issue-preflight 'modelcontextprotocol/python-sdk#3656'
```

没有 pipx 时可在虚拟环境安装，无需 Git：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install https://github.com/jovial-liu/issue-preflight/releases/download/v0.1.1/issue_preflight-0.1.1-py3-none-any.whl
python -m issue_preflight 'OWNER/REPO#123'
```

默认评估当前 `gh` 登录用户，报告会显示该身份；`--actor 用户名` 可以指定其他贡献者。身份识别失败会显示为证据缺口。

也支持完整 issue URL。输出 JSON，供 Agent 或脚本读取：

```bash
issue-preflight 'OWNER/REPO#123' --format json --output report.json --fail-on-review
```

| 判断 | 含义 |
| --- | --- |
| `hold` | 发现阻碍，先读来源再决定是否实施 |
| `review` | 需要复核关联 PR、认领状态、规则或证据缺口 |
| `no_obvious_blockers` | 本次采集未发现明显阻碍，不代表维护者批准或没有竞争实现 |

`--fail-on-hold` 在 `hold` 时返回退出码 2；`--fail-on-review` 在 `hold` 或 `review`（包括证据缺口）时返回 2，仍输出报告。正常报告默认返回 0；必要 API、输入或认证失败返回 1。

## 检查范围

- issue 的开启状态、认领人和标签。
- 时间线、讨论和搜索中出现的 PR，包括已关闭 PR。
- PR 是否明确声明修复当前 issue，避免把 `#12` 和 `#123` 混为一谈。
- 固定同一提交读取 `CONTRIBUTING.md`、`AGENTS.md` 和部分本地贡献指南链接，检测到的规则带具体行号与原文片段。
- 维护者明确提出的停止提交要求。
- API 失败、分页和数量上限造成的证据缺口。

规则判断是启发式的，目前主要识别英文规则。常见代码示例和 HTML 注释会被排除，但没有实现完整 Markdown 解析器。不同措辞、可信贡献者例外、站外政策和没有互相引用的重复实现仍需人工判断。当前 REST 扫描不能解析 Development 栏中的现有手工关联，也不从提交信息推断修复；手工关联事件会列为缺口。报告会保留来源与缺口；搜索无结果不能证明没人做。

完整边界、开发方式与测试说明见 [English README](README.md)。扫描私人仓库的报告可能包含私人项目元数据，请自行决定保存与分享的位置。

MIT 协议。使用 OpenAI Codex 开发，由 [jovial-liu](https://github.com/jovial-liu) 维护。
