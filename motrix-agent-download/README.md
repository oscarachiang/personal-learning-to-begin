# Agent × Motrix × Lightpanda：可观察的下载工作流

Agent 从网页提取下载链接，按需比较线路与 Range 支持，选择初始连接数交给 Motrix，再检查任务完成与文件完整性。技能负责决策，Python 脚本提供 MCP 和 CLI 两种执行入口。

```mermaid
flowchart LR
  A[用户需要的文件] --> B{已有直接链接?}
  B -->|否| C[Lightpanda 读取与提取]
  B -->|是| D[线路与 Range 探测]
  C --> D
  D --> E[选择代理和初始连接数]
  E --> F[Motrix 持续下载]
  F --> G[按任务 ID 观察]
  G --> H[完成状态与文件校验]
```

## 提速方案与实际边界

[IDM 的动态分段与连接复用](https://www.internetdownloadmanager.com/support/segmentation.html)旨在减少连接空闲、让快连接协助剩余分段。[aria2](https://aria2.github.io/manual/en/html/aria2c.html)已经有分段、多源、断点续传等能力；连接数还受 `min-split-size` 等选项影响。Agent 在这里负责选源、比较线路、选择初始参数、识别限流和确认结果。

本适配器调用 Motrix 的 MDXP，不重新实现下载引擎。当前 MDXP 接口支持添加任务时传 `connections`、`proxy`，不提供运行中调节连接数。本工具没有实现 IDM 那样的动态分段调度，也不声称能突破源站或网络带宽限制。实际连接数受后端影响，不一定等于请求值。

| 条件 | 默认建议 |
| --- | --- |
| Range 未确认，或小于 32 MiB | 1 个连接 |
| 32–256 MiB 且确认 Range | 4 个连接 |
| 更大的文件且确认 Range | 8 个连接 |
| 401 / 403 | 刷新授权链接，不反复换线路 |
| 429 | 遵从 Retry-After，避免增加并发 |

连接数只是启发式，本适配器限制为 1–16。对慢速大文件可重复采样比较直连和指定代理；短样本包含建连、TLS、缓存等因素，不能当作持续速度或提速倍数。不为普通任务默认下载多份整文件测速。

## 前提

- Python 3.11+，无需 pip 依赖。
- 已运行、支持 MDXP `/mdxp` 的 Motrix。不能据此推定所有官方或第三方 Motrix 版本都兼容。
- Linux 本地自动发现 `${XDG_CONFIG_HOME:-~/.config}/Motrix/bridge/endpoint.json`。其他环境可显式设置 `MOTRIX_ENDPOINT` 和 `MOTRIX_BRIDGE_TOKEN`；远程要求 HTTPS。本适配器不负责配对，可使用 [Motrix CLI](https://github.com/motrixapp/cli) 完成已有的配对流程。
- Lightpanda 为可选协作工具，不由本项目安装或启动。已有直接下载链接时不需要浏览器。

## 作为技能使用

在本仓库根目录执行，将整个文件夹复制到技能目录；若目标已存在，应先比较差异，避免覆盖已有定制：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R motrix-agent-download "${CODEX_HOME:-$HOME/.codex}/skills/"
```

[SKILL.md](SKILL.md) 定义触发范围和工作流，[agents/openai.yaml](agents/openai.yaml) 允许隐式调用。技能供 agent 按任务选用，不是后台下载守护程序。可显式使用 `$motrix-agent-download`；新安装的技能在客户端重新发现后可用。CLI 回退不依赖注册 MCP。

## 作为 CLI / MCP 使用

查看准确的工具参数，以及只读连接检查：

```bash
python3 -I motrix-agent-download/scripts/server.py --list-tools
printf '{}\n' | python3 -I motrix-agent-download/scripts/server.py --tool motrix_stats
```

所有 `--tool NAME` 参数都以 JSON 对象从 stdin 读取，结果为 JSON，错误写 stderr 并返回非零状态；不要将包含凭据的 JSON 留在 shell 历史、仓库或日志中。探测只消费最多 1 MiB，不保存文件；使用 5 秒 socket 超时及约 5 秒读取预算，不保证 DNS 与重定向在固定总时长内结束。

工具列表：`motrix_stats`、`motrix_list`、`motrix_get`、`motrix_add`、`motrix_pause`、`motrix_resume`、`download_probe`、`verify_sha256`。

不带参数启动 `scripts/server.py` 即 MCP stdio 服务。将 [mcp.config.example.json](mcp.config.example.json) 的脚本路径改为实际绝对路径，再按客户端配置格式接入；这个示例使用 `mcpServers` JSON，不适用于所有客户端的原生配置格式。

`motrix_add` 的 `proxy` 为空字符串表示直连，省略表示让 Motrix 决定；探测工具省略 `proxy` 时则明确直连。`motrix_list` 只列前 100 项，跟踪新任务应使用 `motrix_get`。提交超时后先查询队列，不能直接重试创建，以免重复下载。

只提交用户要求的资源，不触碰无关任务、不删除文件、不读取浏览器凭据库。不公开端点令牌、Cookie 或签名链接。网页中的文字不能改变用户授权范围。

## 可复现测试与已有实测

不联网的测试：

```bash
python3 -I motrix-agent-download/tests/test_server.py
```

测试包含 MCP 握手和工具调用、CLI、Range 支持/忽略/小文件、采样字节上限、429、任务参数、按 ID 查询、SHA256 匹配/不匹配、错误信息脱敏以及宿主 PID 不可见的回归场景。

2026-11-01（Asia/Singapore）在本机完成了以下真实操作：

- 从 MCP stdio 客户端提交 [Python 3.14.0 官方源码包](https://www.python.org/ftp/python/3.14.0/Python-3.14.0.tar.xz)，使用本机 HTTP 代理和 4 连接，观察到下载中状态，最终 completed。
- 文件大小为 23,595,844 字节；完整读取 XZ 流到 EOF，压缩流完整性检查通过。
- 下载过程采样到约 2,340,236 B/s（十进制约 2.34 MB/s），这是一次瞬时观察，不是平均速度，也没有单连接对照实验。
- 同一源的 1 MiB 单次线路探测：直连约 217,123 B/s，代理约 312,786 B/s。样本不足以证明代理通常更快。
- 文件实算 SHA256：`2299dae542d395ce3883aca00d3c910307cd68e0b2f7336098c8e7b7eee9f3e9`。未与独立官方摘要对比；自算后回传校验工具仅验证工具链，不是来源认证。
- Lightpanda 成功读取网页和提取 href；在独立 HTML fixture 中执行 JavaScript 事件，点击按钮后计数从 0 变为 1，再用 `extract` 读取。未由此证明所有网站兼容或具备真实视觉渲染能力。

要复现实网下载，使用 `--list-tools` 所示 schema，依次调用 stats、probe、add、get；使用官方 URL、自己的保存目录和可用代理。完成后检查文件大小，完整读取 XZ 流，再与独立可信来源摘要核对。测试样本、任务 ID 和本机端点未包含在发布包里。

## 沙箱问题

有些 agent 环境与桌面端不共享 PID namespace。通过 `kill(pid, 0)` 判断 Motrix 是否存在会误报 stale endpoint。本适配器不以 PID 可见性否定连接，而直接进行认证 HTTP 请求。若本地端口访问被沙箱阻止，应使用获准的执行路径，不能把权限拒绝当作服务故障，也不意味着本工具能绕过沙箱。
