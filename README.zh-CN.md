# Issue Preflight

**让 AI 开始修 GitHub issue 前，先核对贡献证据。**

[English](README.md)

“issue 还开着”不代表没人修。已有 PR 可能被自动关闭，贡献规则也可能要求认领、人工复核或提前讨论。Issue Preflight 汇总这些证据，生成带来源链接的 Markdown / JSON 报告，供你和代码 Agent 做开工判断。

本地运行，使用已有 `gh` 登录，Python 运行时零第三方依赖，不需要模型 API Key。GitHub 请求均为 GET，不会自动留言、认领、建分支或提交 PR。

## 安装与使用

需要 Python 3.10+ 和 [GitHub CLI](https://cli.github.com/)。

```bash
gh auth login
pipx install git+https://github.com/jovial-liu/issue-preflight.git
issue-preflight 'modelcontextprotocol/python-sdk#3656' --actor 你的GitHub用户名
```

也支持完整 issue URL。输出 JSON，供 Agent 或脚本读取：

```bash
issue-preflight 'OWNER/REPO#123' --format json --output report.json --fail-on-hold
```

| 判断 | 含义 |
| --- | --- |
| `hold` | 发现阻碍，先读来源再决定是否实施 |
| `review` | 需要复核关联 PR、认领状态、规则或证据缺口 |
| `no_obvious_blockers` | 本次采集未发现明显阻碍，不代表维护者批准或没有竞争实现 |

`--fail-on-hold` 在 `hold` 时返回退出码 2；正常报告默认返回 0；必要 API、输入或认证失败返回 1。

## 检查范围

- issue 的开启状态、认领人和标签。
- 时间线、讨论和搜索中出现的 PR，包括已关闭 PR。
- PR 是否明确声明修复当前 issue，避免把 `#12` 和 `#123` 混为一谈。
- 固定同一提交读取 `CONTRIBUTING.md`、`AGENTS.md` 和部分本地贡献指南链接。
- 维护者明确提出的停止提交要求。
- API 失败、分页和数量上限造成的证据缺口。

规则判断是启发式的，目前主要识别英文规则。不同措辞、可信贡献者例外、站外政策和没有互相引用的重复实现仍需人工判断。报告会保留来源与缺口；搜索无结果不能证明没人做。

完整边界、开发方式与测试说明见 [English README](README.md)。扫描私人仓库的报告可能包含私人项目元数据，请自行决定保存与分享的位置。

MIT 协议。使用 OpenAI Codex 开发，由 [jovial-liu](https://github.com/jovial-liu) 维护。
