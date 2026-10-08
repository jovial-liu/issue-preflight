# Issue Preflight

**让 AI 开始修 GitHub issue 前，先核对贡献证据。**

[English](README.md)

“issue 还开着”不代表没人修。已有 PR 可能被自动关闭，贡献规则也可能要求认领、人工复核或提前讨论。Issue Preflight 汇总这些证据，生成带来源链接的 Markdown / JSON 报告，供你和代码 Agent 做开工判断。

本地运行，使用已有 `gh` 登录，Python 运行时零第三方依赖，不需要模型 API Key。GitHub 请求均为 GET，不会自动留言、认领、建分支或提交 PR。

## 安装与使用

需要 Python 3.10+ 和 [GitHub CLI](https://cli.github.com/)。下面第一种方式还需要 [pipx](https://pipx.pypa.io/stable/installation/)。

```bash
gh auth login
pipx install https://github.com/jovial-liu/issue-preflight/releases/download/v0.1.2/issue_preflight-0.1.2-py3-none-any.whl
issue-preflight 'modelcontextprotocol/python-sdk#3656'
```

没有 pipx 时可在虚拟环境安装，无需 Git：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install https://github.com/jovial-liu/issue-preflight/releases/download/v0.1.2/issue_preflight-0.1.2-py3-none-any.whl
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
- 固定同一提交读取贡献指南、`AGENTS.md` 和明确链接的政策，检测到的规则带具体行号与原文片段。
- 维护者明确提出的停止提交要求。
- API 失败、分页和数量上限造成的证据缺口。

扫描先探测 `CONTRIBUTING.md`、`.github/CONTRIBUTING.md` 和 `AGENTS.md`，再跟随可识别的 AI、Agent 和贡献政策链接，包括引用式链接。同仓库且受支持的文本文件可以通过相对路径、父目录（不能越过仓库根目录）、根路径或 GitHub `blob` URL 引用；读取一律使用本轮固定的提交，不使用链接中的旧分支或旧 SHA。总计最多 **六次 contents 请求**，包含默认探测、404 和失败请求。明确链接的文件不存在、无法读取、类型不支持、位于外部或路径有歧义时，都会记录证据缺口。

`approval_policy` 属于 `review`：检测到的规则要求 PR 链接到包含维护者已批准方案的 issue 或 discussion。需要阅读原文与适用范围，例如规则可能专门针对 AI 生成的贡献。扫描没有核验是否已经存在获批方案。

## 真实案例

此前扫描 `Textualize/rich#4225` 已因关联 PR 关闭而得到 `review`，但漏读了 AI 政策。在固定提交 `9d8f9a372cc5916fd4781fec207ced7ddac2f08f` 中，[CONTRIBUTING.md 第 9 行](https://github.com/Textualize/rich/blob/9d8f9a372cc5916fd4781fec207ced7ddac2f08f/CONTRIBUTING.md#L9) 链接到 `master/AI_POLICY.md`。v0.1.2 会在同一固定提交读取该文件，并补出[第 5 行](https://github.com/Textualize/rich/blob/9d8f9a372cc5916fd4781fec207ced7ddac2f08f/AI_POLICY.md#L5)针对 AI 生成 PR 的方案审批规则。查看[政策报告快照](examples/rich-ai-policy.md)；报告引用要求，没有核验方案是否已经获批。

## 边界

规则判断是启发式的，目前主要识别英文规则。常见代码示例和 HTML 注释会被排除，但文本处理和链接发现没有实现完整 Markdown 解析器。未知 ref 加多级文件路径的 `blob` URL 可能有歧义，会记录为缺口。不同措辞、可信贡献者例外、站外政策和没有互相引用的重复实现仍需人工判断。当前 REST 扫描不能解析 Development 栏中的现有手工关联，也不从提交信息推断修复；手工关联事件会列为缺口。报告会保留来源与缺口；搜索无结果不能证明没人做。

完整边界、开发方式与测试说明见 [English README](README.md)。扫描私人仓库的报告可能包含私人项目元数据，请自行决定保存与分享的位置。

MIT 协议。使用 OpenAI Codex 开发，由 [jovial-liu](https://github.com/jovial-liu) 维护。
