---
name: motrix-agent-download
description: 用 Motrix 执行可观察的下载与慢速诊断，结合 Lightpanda 查找下载链接、有限采样比较直连和代理、选择初始连接数并验证完成。适用于大文件、GUI 队列及网页到下载器的协作任务；小型接口请求直接使用 HTTP 工具。
---

# Motrix 与浏览器下载协作

当用户要下载文件、排查 Motrix 慢速，或从网页寻找资源后下载时使用。默认中文。用户指定其他下载器时遵从，不因本技能改变工具选择。

## 可执行入口

本技能内的 `scripts/server.py` 同时提供 MCP stdio 和一次性 CLI，Python 3.11+，只使用标准库。

- MCP 工具可用时直接调用；否则从本技能目录解析脚本绝对路径，执行 `python3 -I <skill-dir>/scripts/server.py --tool TOOL`，参数作为一个 JSON 对象写入 stdin，结果为 JSON。不要把签名 URL 或令牌放入 shell 参数、文件或日志。
- `--list-tools` 输出精确参数 schema；无参数启动是 MCP stdio 服务。无需修改客户端配置也可通过 CLI 完成任务。
- 本地端点从 `${XDG_CONFIG_HOME:-~/.config}/Motrix/bridge/endpoint.json` 发现。文件及令牌只由脚本读取，不打印。远程端点通过 `MOTRIX_ENDPOINT`、`MOTRIX_BRIDGE_TOKEN` 环境变量传入；非回环地址要求 HTTPS。

## 按需执行

1. 明确用户所需资源、绝对保存目录和文件名。已有直接 URL 就跳过浏览器。需要读网页时，优先服务的专用工具；通用页面用可用的 Lightpanda：先 `tree`，定位下载链接后 `nodeDetails` / `extract` 得到 href。动态内容不完整时作一次针对性等待。需要真实视觉验收或指定登录标签页时使用对应浏览器；不假定 Lightpanda 共享登录态。
2. `motrix_stats` 检查连接。沙箱进程列表可能看不到 Motrix 的宿主 PID，CLI 的 “stale endpoint” 不是进程已退出的充分证据。本脚本直接以认证 HTTP 请求判断连接；本地网络遭拒时走执行环境允许的权限流程，不修改端点或杀进程。缺少 bridge 时报告兼容性问题，不把所有 Motrix 版本都当作支持 MDXP。
3. 对待下载 URL 调用 `download_probe`。默认直连；仅比较用户提供或当前任务已明确的代理。探测最多消费 1 MiB，不落盘；有 5 秒 socket 超时和约 5 秒读取预算，DNS/重定向可能延长总时长。对大文件或慢速诊断，可每条线路重复 2–3 次，比较中位数；小文件避免探测成本超过下载本身。
4. 以 `suggested_initial_connections` 为起点：未确认 Range 或文件小于 32 MiB 用 1，32–256 MiB 用 4，更大用 8。本适配器上限为 16；建议是启发式。401/403 刷新合法链接；429 遵从 Retry-After，不靠增加连接重试。短样本速度不等于持续吞吐；已有完成记录可辅助判断。用户已授权测试时可调整初始并发作对照，不为日常下载重复下载整文件。
5. 用 `motrix_add` 提交，明确 `proxy`：空字符串直连，地址为指定代理，省略由 Motrix 决定。返回 ID 立即保存于当前任务上下文。提交超时不盲目再提交，先查队列。MDXP 不能运行中修改连接数；不为调参自动重建任务、删除文件或暂停其他任务。
6. 优先 `motrix_get(task_id)` 定位任务，`motrix_list` 仅返回前 100 项。每次观察有时间上限；报告 bytesDone、bytesTotal、speedBps 和状态。只有 completed 且最终文件存在才称完成；可信官方 SHA256 可用时再调用 `verify_sha256`。自算摘要相互比较不等于官方认证。失败保留部分文件，明确原因和下一步。

不合并未经确认的镜像；同名、同大小都不足以证明内容相同。不读取浏览器凭据库，不下载后自动安装或执行。

## 工具范围

`motrix_stats`、`motrix_list`、`motrix_get`、`motrix_add`、`motrix_pause`、`motrix_resume`、`download_probe`、`verify_sha256`。暂停/恢复仅针对用户要求的任务。磁力、种子及其他 MDXP 方法交给已有 Motrix CLI 或对应技能；本适配器只提交 HTTP(S) 文件。
