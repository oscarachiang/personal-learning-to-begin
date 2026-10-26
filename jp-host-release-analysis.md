# `jp-host-release.apk` 静态逆向分析报告

> 分析时间：2026-10-24  
> 样本：`/home/elin/Downloads/ABDM/Programs/jp-host-release.apk`  
> 分析方式：只读样本 + 本地反编译（apktool、jadx），未修改原始 APK。  
> SHA-256：`529671f4e6deb04a23ff1ec343ff7d49d67de364c0773a0a1d98077a0749e7b1`

## 1. 结论概要

这是一个**混合宿主 + 动态 Web runtime** 应用：

- 包名：`com.jp.app`
- 显示名：`荐片`
- 版本：`5.0.75` / `versionCode 5075`
- minSdk / targetSdk：`24 / 36`
- 宿主负责启动、保活、下载管理、播放器、运行时更新与 native 桥接。
- 实际业务界面主要在 `assets/web-bundle.zip` 中，通过 WebView 加载本地可信 URL：
  `https://appassets.androidplatform.net/runtime/index.html`
- DEX 有 R8 重命名/混淆，但没有壳、VM 保护或 DEX 加密；用 jadx 基本可以还原主要逻辑。
- Web 资源未加密，只有 zip 内 `bundle-manifest.json` 记录 SHA-256；APK 本身有签名保护。
- 动态 runtime 更新采用 ECDSA P-256 双签、阈值 2、过期/回滚/协议/工件完整性校验。
- native 库只有标准 AndroidX graphics path 和友盟 `umid` 相关库，没有发现自研加固/解密/反调试 so。

## 2. AndroidManifest 要点

关键配置：

```text
package: com.jp.app
application name: com.jp.bootstrap.JpApplication
main activity: com.jp.bootstrap.MainActivity
processes: 主进程 + :plugin
allowBackup: false
debuggable: 未显式开启，默认 false
networkSecurityConfig: @xml/jp_network_security_config
```

导出的业务组件很少：

- `com.jp.bootstrap.MainActivity`，launcher
- `androidx.profileinstaller.ProfileInstallReceiver`，由系统 profile installer 使用

未导出组件包括 runtime 更新 receiver、插件进程 service、容器 Activity、provider、播放器 Activity 等。

### 权限

```text
INTERNET
ACCESS_NETWORK_STATE
ACCESS_WIFI_STATE
CHANGE_WIFI_MULTICAST_STATE
FOREGROUND_SERVICE
FOREGROUND_SERVICE_DATA_SYNC
FOREGROUND_SERVICE_MEDIA_PLAYBACK
POST_NOTIFICATIONS
WAKE_LOCK
CAMERA
WRITE_EXTERNAL_STORAGE  # maxSdkVersion=28
com.google.android.gms.permission.AD_ID
freemme.permission.msa
```

主要用途与功能相符：网络请求、下载/保活、媒体播放、通知、投播发现、相机/文件选择桥接。`AD_ID` 与 `freemme.permission.msa` 表明存在广告/统计/设备标识能力。

## 3. 整体架构

### 3.1 宿主与插件进程

`JpApplication` 初始化：

1. 绑定 host services。
2. 对 `:plugin` 进程设置独立 WebView data directory suffix。
3. 使用 Tencent Shadow 的 `DynamicRuntime.recoveryRuntime()` 恢复插件 runtime。
4. 初始化 `runtime-releases` 的 `ReleaseSlotStore`。
5. 校验资源字符串 `jp_build_identity` 与 `JpBuildIdentity.TOKEN`：
   `3786c522fe83b62e001458926a956a502ca2580e4cba3632e896aa2be3b19a17`
6. 初始化 runtime update manager。

`:plugin` 进程承载：

- `JpPluginProcessService`
- `JpRuntimeContainerProvider`
- `RuntimeApiEndpointProvider`
- `RuntimeAnalyticsBridgeProvider`
- `JpPluginContainerActivity`
- `JpDataSyncKeepAliveService`
- `PluginPlaybackKeepAliveService`

### 3.2 Web runtime

APK 内置：

```text
assets/builtin-runtime.json
assets/web-bundle.zip
assets/jp-release-root.json
assets/jp-build/3786c522fe83b62e.bin
```

`builtin-runtime.json`：

```json
{
  "format": 2,
  "releaseSetId": "20261023-145451-all",
  "version": 5075,
  "runtimeProtocol": 2,
  "web": {
    "path": "web-bundle.zip",
    "length": 1922199,
    "sha256": "6a65427c93f7c39d1a3dd1d69d6044ef0ce259081ebfa02fbaa505e2b09ccdb8"
  }
}
```

`web-bundle.zip` 中的 `bundle-manifest.json` 对每个文件记录 SHA-256，本次校验全部通过。

WebView 加载地址被限制为：

```text
https://appassets.androidplatform.net/runtime/index.html
```

非 `appassets.androidplatform.net/runtime/...` 的 URL 会转交给外部打开。

## 4. 签名与完整性

JAR 证书：

```text
CN=JP Android Release, OU=Mobile, O=JP, L=Shanghai, ST=Shanghai, C=CN
SHA-256:
21:E4:60:94:71:88:90:D8:78:8B:39:B3:38:2E:DC:34:2E:A3:10:93:66:68:CB:EC:A5:CD:A2:64:42:05:E6:62
算法: RSA-4096 / SHA256withRSA
自签名
```

APK 内部存在 `APK Sig Block 42` 标记，说明除 v1 JAR signature 外还包含 v2/v3 系 signing block。`jarsigner -verify` 对 JAR 层验证通过。

## 5. 动态 runtime 更新链路

关键类：

```text
com.jp.release.ReleaseVerifier
com.jp.release.ReleaseManifestParser
com.jp.release.ReleaseSlotStore
com.jp.release.ArtifactIntegrity
com.jp.release.WebBundleArchive
com.jp.bootstrap.internal.d00
com.jp.bootstrap.internal.ytcoom
```

校验流程大致为：

1. 下载 release manifest 与工件到 `no_backup_files_dir/runtime-update-staging`。
2. 解析 `{"signed":..., "signatures":[...]}` 信封。
3. 检查：
   - `_type == jp-release-set-v1`
   - `releaseSetId`
   - `version`
   - `expires`
   - `minHostApi`
   - `runtimeProtocol`
4. 对 canonical `signed` JSON 做 `SHA256withECDSA` 验签。
5. 至少需要两个不同可信 key 签名通过，阈值来自：
   `assets/jp-release-root.json` 中的 `threshold: 2`
6. 校验 artifact 完整性。
7. 安装到 A/B slot，激活 pending release。
8. 运行成功后由健康检查确认，失败则记录 core failure / 隔离 / 回滚。

可信根内含两把 P-256 公钥，keyid 分别为：

```text
8bdc32b8be0396db6484a3fdb2025fef70b2b3058b43365ec15c42cee5756750
edb8bd9cdaaf7a40a064562cacbbca743b6ca84ccb40b1d5cb086c476a52a033
```

## 6. Web bundle 业务与 native 桥

### 6.1 前端结构

`web-bundle.zip`：

```text
index.html
fs-lab.html
assets/app-modern.js
assets/app-legacy.js
assets/index-DGDal8_L.css
assets/index-DGDal8_L.legacy.css
logo.png
bundle-manifest.json
...
```

`index.html` 使用 CSP：

```text
default-src 'self';
script-src 'self' data: 'nonce-...';
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob: https:;
connect-src 'self' https:;
media-src 'self' https: blob:;
worker-src 'self' blob:;
object-src 'none';
base-uri 'none'
```

前端通过 `window.jpBridge.postMessage()` 调 native，兼容 `window.Android` 与 iOS message handler。

### 6.2 主要桥接方法

从现代 bundle 中可见的方法名包括：

```text
api.request
api.secureRequest
api.cancel
api.endpoint
api.invalidateEndpoint
api.invalidateEnrollment
device.identity
auth.sync
auth.restore
update.check
update.status
update.apply
player.open / player.embed / player.update / player.layout / player.close
player.overlay
adult.policy
shorts.open / shorts.prepare / shorts.warm / shorts.command / shorts.layout / shorts.visibility
cast.open / cast.command
downloads.command / downloads.enqueueBatch / downloads.enqueueIntents / downloads.commandBatch
downloads.settings
cache.admin
splash.release
ui.setWebViewOpaque
```

Native 侧 `TrustedLocalWebRuntime` 会校验 bridge JSON、path、method、header、body 长度等。

普通 API 允许相对路径 `/api/...`，安全 API 必须是 `/api/v1/...`。允许方法：

```text
GET, POST, PUT, PATCH, DELETE, HEAD
```

body 上限约 6 MiB；header 数量上限 32，header 值上限 8192 字节，且禁止 CRLF。

## 7. API 加密与签名

相关类：

```text
com.jp.runtime.web.RuntimeEncryptedApiClient
com.jp.runtime.web.RuntimeEncryptedApiClientKt
```

每个安装会生成本地 identity：

- `installation_id`：UUID
- `credential`：32 字节随机数，Base64 存储

key 派生：

```text
root = SHA256("jp-api-v1\0" + deviceId)
seed = HMAC-SHA256(key=root, message=credential)
requestAuthKey    = HMAC-SHA256(key=seed, message="jp-api-request-auth-v1" + 0x01)
requestBodyKey    = HMAC-SHA256(key=seed, message="jp-api-request-body-v1" + 0x01)
responseBodyKey   = HMAC-SHA256(key=seed, message="jp-api-response-body-v1" + 0x01)
```

请求头：

```text
X-Device-ID
X-JP-Runtime-Authorization: Bearer <credential>
X-JP-Crypto-Version: 1
X-JP-Timestamp
X-JP-Nonce
X-JP-Signature
```

签名输入：

```text
METHOD
request path
unix timestamp
base64(nonce)
hex(sha256(body))
```

签名算法：

```text
Base64(HMAC-SHA256(requestAuthKey, signatureInput))
```

加密请求 envelope：

```json
{
  "v": 1,
  "alg": "A256GCM",
  "ts": 1234567890,
  "data": "<base64 AES-256-GCM ciphertext+tag>"
}
```

请求体 AAD：

```text
jp-api-request-v1
METHOD
request path
timestamp
base64(nonce)
installation_id
```

响应解密 AAD：

```text
jp-api-response-v1
METHOD
request path
HTTP status
timestamp
base64(nonce)
installation_id
```

加密算法为 AES-256-GCM，nonce 12 字节，tag 128 bit。

## 8. API endpoint 发现机制

静态可见 endpoint discovery 配置：

```text
https://ssopj-1462720388.cos.accelerate.myqcloud.com/config.txt
hodpj.cc  # 通过 TXT 记录发现
```

静态内置候选 API 域名：

```text
bdgnbrws.com
fvevfbr.com
swgsdfew.com
```

备用 DoH：

```text
https://dns.alidns.com/resolve
https://doh.pub/dns-query
https://cloudflare-dns.com/dns-query
```

resolver 会并行探测候选、保存 last-good origin、按网络记录 latency/请求 EWMA，并处理失败切换。前端也能通过 `api.invalidateEndpoint` 触发切换。

## 9. native 库分析

### `libandroidx.graphics.path.so`

- 标准 AndroidX graphics path native 实现。
- NDK r25c 构建。
- 只见 `JNI_OnLoad`，未发现敏感字符串或自研逻辑。

### `libumeng-spy.so`

- 友盟 UMID 组件。
- 导出：
  - `Java_com_umeng_umzid_Spy_getNativeID`
  - `Java_com_umeng_umzid_Spy_getNativeLibraryVersion`
  - `Java_com_umeng_umzid_Spy_getNativeTag`
- 未发现网络、加密、shell、root、frida 相关字符串。

没有自研加固、业务解密或反调试 native 库。

## 10. 安全与逆向观察

### 逆向难度

- DEX 只做了 R8 混淆，未发现壳保护。
- `com.jp.bootstrap.internal.*` 命名随机，但 jadx 输出可读。
- Web bundle 完全明文，较容易分析。
- native 层简单，主要逻辑在 Java/Kotlin 和 JS。
- 静态分析成本低；主要难度在于代码量大和 endpoint 动态选择。

### 保护强度

有效保护：

- APK 签名。
- 动态 runtime release 双签。
- 更新回滚与过期控制。
- Web bundle 文件级 SHA-256。
- API 请求 HMAC 签名与 AES-GCM body 加密。
- WebView 只允许可信 runtime URL，外链外部打开。

局限：

- 内置 web bundle 是明文。
- API credential 保存在本地 SharedPreferences，设备侧可被 root/备份路径提取。
- API crypto 本质是客户端可复现方案，不能视为服务器对可信客户端的强认证。
- `network_security_config` 允许 cleartext traffic，虽然 runtime endpoint resolver 强制 HTTPS，但媒体或第三方请求仍可能使用 HTTP。
- WebView 开启了：
  - `setAllowFileAccessFromFileURLs(true)`
  - `setAllowUniversalAccessFromFileURLs(true)`

  由于实际加载的是 `https://appassets...` 且 URL 白名单较严，风险受控，但不是最小权限配置。

## 11. 建议后续工作

1. 在隔离 Android 环境/模拟器中运行，抓取：
   - `JpBootstrap` / `JpWebRuntime` / `JpApiTiming`
   - `api.endpoint` bridge 消息
   - WebView bridge JSON
2. 如需确认线上 endpoint，可访问或代理 `config.txt` 与 DoH TXT 响应。
3. 对 `api.secureRequest` 做动态抓包，确认 `X-JP-Signature` 与 body envelope。
4. 用 `adb shell dumpsys activity top` 观察 plugin 容器。
5. 用 `run-as com.jp.app` 或 root 环境检查：
   - `shared_prefs/runtime-device-identity.xml`
   - `shared_prefs/api-endpoint-resolver.xml`
   - `no_backup_files_dir/runtime-releases`
6. 若做作业演示，可重点写清“客户端侧 API 加密不能防合法客户端用户提取/重放，只能提高直接 HTTP 请求门槛”。

## 12. 本地工作目录

反编译与解包结果保留在：

```text
/home/elin/Documents/Codex/2026-10-24/w-2/work/apktool_out
/home/elin/Documents/Codex/2026-10-24/w-2/work/jadx_out
/home/elin/Documents/Codex/2026-10-24/w-2/work/webbundle
/home/elin/Documents/Codex/2026-10-24/w-2/work/libs
```
