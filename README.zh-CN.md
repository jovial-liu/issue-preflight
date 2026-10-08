# Issue Preflight

**让 AI 开始修 GitHub issue 前，先核对贡献证据。**

[English](README.md)

“issue 还开着”不代表没人修。已有 PR 可能被自动关闭，贡献规则也可能要求认领、人工复核或提前讨论。Issue Preflight 汇总这些证据，生成带来源链接的 Markdown / JSON 报告，供你和代码 Agent 做开工判断。

本地运行，使用已有 `gh` 登录，Python 运行时零第三方依赖，不需要模型 API Key。GitHub 请求均为 GET，不会自动留言、认领、建分支或提交 PR。

## 安装与使用

需要 Python 3.10+ 和 [GitHub CLI](https://cli.github.com/)。下面第一种方式还需要 [pipx](https://pipx.pypa.io/stable/installation/)。

```bash
gh auth login
pipx install https://github.com/jovial-liu/issue-preflight/releases/download/v0.2.2/issue_preflight-0.2.2-py3-none-any.whl
issue-preflight 'modelcontextprotocol/python-sdk#3656'
```

没有 pipx 时可在虚拟环境安装，无需 Git：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install https://github.com/jovial-liu/issue-preflight/releases/download/v0.2.2/issue_preflight-0.2.2-py3-none-any.whl
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

Codex / Claude Code 可以使用仓库内的 [Issue Preflight 技能](skills/issue-preflight/SKILL.md)。将它复制到目标项目的技能目录，位置与调用方式见[安装说明](docs/agent-skill.md)。技能调用现有 CLI，无需 MCP 服务；客户端自动发现与调用尚未做端到端验证。

## 检查范围

- issue 的开启状态、认领人和标签。
- 时间线、讨论和搜索中出现的 PR，包括已关闭 PR。
- PR 是否明确声明修复当前 issue，避免把 `#12` 和 `#123` 混为一谈。
- 固定同一提交读取贡献指南、`AGENTS.md` 和明确链接的政策，检测到的规则带具体行号与原文片段。
- 维护者明确提出的停止提交要求。
- API 失败、分页和数量上限造成的证据缺口。

主探测路径是 `CONTRIBUTING.md`、`.github/CONTRIBUTING.md` 和 `AGENTS.md`。已发现的明确 AI、Agent 和贡献政策链接优先于剩余探测，包括引用式链接。未读到非空白贡献指南时，还会尝试 `docs/contributing.md`、`docs/contributing.rst`；仅有 `AGENTS.md` 不会取消贡献指南的回退查找。同仓库且受支持的文本文件可以通过相对路径、父目录（不能越过仓库根目录）、根路径或 GitHub `blob` URL 引用；读取一律使用本轮固定的提交，不使用链接中的旧分支或旧 SHA。总计最多 **六次 contents 请求**，包含默认探测、404 和失败请求。明确链接的文件不存在、无法读取、类型不支持、位于外部或路径有歧义时，都会记录证据缺口；达到上限后仍未读取的有效探测路径，以及只读到空白文件的情况，也会留下缺口。

RST 文件会保留固定提交的来源链接，并列出格式限制，要求人工阅读。RST 的注释、示例和指令语法不同，当前 Markdown 规则分类器不会自动判断其中的规则，也不解析 RST 原生链接。

`help wanted` 或 `prs welcome` 标签只有在指南紧邻该标签明确规定受支持的认领豁免时，才会免除已识别的认领要求。标签清单、注释、代码示例和其他权限说明均不足以豁免；措辞含糊时保留认领阻断，供使用者阅读固定提交的来源。

`approval_policy` 属于 `review`：检测到的规则要求 PR 链接到包含维护者已批准方案的 issue 或 discussion。需要阅读原文与适用范围，例如规则可能专门针对 AI 生成的贡献。扫描没有核验是否已经存在获批方案。

读取 PR 详情前会合并仓库名的大小写变体，并优先检查已知仓库名与目标一致的候选；各组内部保留发现顺序，失败请求仍占详情预算。尚未读取的旧仓库重定向别名无法预先获得此优先级。详情读取后，报告使用实际 base 仓库身份。外仓库且未声明关闭当前 issue 的 PR，无论开启、关闭或合并，都作为相关性尚未核验的引用展示。

## 真实案例

此前扫描 `Textualize/rich#4225` 已因关联 PR 关闭而得到 `review`，但漏读了 AI 政策。在固定提交 `9d8f9a372cc5916fd4781fec207ced7ddac2f08f` 中，[CONTRIBUTING.md 第 9 行](https://github.com/Textualize/rich/blob/9d8f9a372cc5916fd4781fec207ced7ddac2f08f/CONTRIBUTING.md#L9) 链接到 `master/AI_POLICY.md`。v0.1.2 会在同一固定提交读取该文件，并补出[第 5 行](https://github.com/Textualize/rich/blob/9d8f9a372cc5916fd4781fec207ced7ddac2f08f/AI_POLICY.md#L5)针对 AI 生成 PR 的方案审批规则。查看[政策报告快照](examples/rich-ai-policy.md)；报告引用要求，没有核验方案是否已经获批。

requests-cache 的贡献指南把“审核、测试并理解”放在“由人类”之前。v0.1.2 能识别这类措辞及常见 Markdown 强调、软换行，并保留原文行号和片段。查看[固定提交的政策示例](examples/requests-cache-human-review.md)，了解原始规则与报告边界。

## 从仓库选择 issue

还没有 issue 编号时，可以使用显式 `scan` 子命令：

```bash
issue-preflight scan OWNER/REPO --limit 5 --format json --output scan.json
```

默认按 GitHub REST 的最近更新时间降序选择前 **5 个 open issue**，排除 PR；`--limit` 支持 1–10。列表最多读取两页，每页 100 条，包含 PR。每个选中 issue 都复用原有的完整证据报告与政策、认领、覆盖判断，包括没有评论但时间线已有 PR 的情况。这里只降低寻找候选的成本，不评估问题价值或建议直接开工。

批量 JSON 使用 `issue-preflight-scan/1`：`results` 每项包含 issue 及完整的原 `issue-preflight/1` 报告，或明确的 `error`；`summary` 分别计数，不给整批“安全”结论。批次内复用成功的仓库信息和固定提交政策请求；每个 issue、评论和时间线仍单独获取。采集期间 issue 可能关闭、列表顺序可能变化；重复编号只选择一次，列表不是原子快照。

| `listing_status` | 含义 | `selection_truncated` |
| --- | --- | --- |
| `exhausted` | 所采集列表已结束，没有发现额外 issue | `false` |
| `selection_limit` | 已看到额外 issue，只选前 N 项 | `true` |
| `page_limit` | 达到两页上限，页外是否还有 issue 未知 | `null` |
| `error` | 列表页获取失败或数据不可用 | `null` |

正常只选前 N 项会单独说明，不冒充 API 失败；页数上限和列表失败写入 `listing_gaps`。每项证据缺口保留在原报告中，身份未知同时写入 `identity_gaps` 和每个成功报告。显式传给 `scan --actor` 的空值或纯空白也标为未知，不会切换成当前登录身份。

原单 issue 命令和退出行为保持兼容。`scan` 的退出规则如下，检查后仍先输出报告：

- 默认：有界报告返回 0，明确显示选择或页数上限。
- `--fail-on-hold`：任一已检查 issue 有阻碍时返回 2。
- `--fail-on-review`：任一 hold/review、身份未知、只选前 N 项或列表缺口时返回 2。
- 列表页或单项必要 API 失败：保留其他结果，返回 1，优先于两个严格选项。输入、仓库查询或文件输出失败也返回 1。

继承 `--actor`、`--max-prs`、`--format` 和 `--output`。所有请求均为 GET；只有明确指定 `--output` 才保存文件。查看 `issue-preflight scan --help` 获取选项。

## 边界

规则判断是启发式的，目前主要识别英文规则。常见代码示例和 HTML 注释会被排除，但文本处理和链接发现没有实现完整 Markdown 解析器。未知 ref 加多级文件路径的 `blob` URL 可能有歧义，会记录为缺口。不同措辞、可信贡献者例外、站外政策和没有互相引用的重复实现仍需人工判断。当前 REST 扫描不能解析 Development 栏中的现有手工关联，也不从提交信息推断修复；手工关联事件会列为缺口。报告会保留来源与缺口；搜索无结果不能证明没人做。

完整边界、开发方式与测试说明见 [English README](README.md)。扫描私人仓库的报告可能包含私人项目元数据，请自行决定保存与分享的位置。

MIT 协议。使用 OpenAI Codex 开发，由 [jovial-liu](https://github.com/jovial-liu) 维护。
