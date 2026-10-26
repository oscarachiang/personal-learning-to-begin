# `jp-host-release-modified-test.apk`

## 用途

这是给作业用的**本地测试改包**，不是对外发布版本。请不要传播。

目标：

1. 禁用服务端可控广告/推广链路。
2. 强制成人内容请求为 `include_adult=false`。
3. 把“伦理专区 / 18+”入口改为“我的设置”。

## 改动点

### Web / 业务层

在 WebView runtime 的 `app-modern.js` / `app-legacy.js` 中做了最小补丁：

- `ads/bootstrap` 请求禁用。
- `ads/events` 事件上报禁用。
- `promo/surfaces/*` legacy 接口禁用。
- 广告素材 preload 禁用。
- `adultContentEnabled` 恒为 `false`。
- `AdultCatalog` 路由整体重定向到 Home（直接访问 `adult` 也会落到首页）。
- 广告组件在 `app-modern.js`、`app-legacy.js` 两套 bundle 里都已处理。
- “伦理专区 / 18+”入口指向“我的设置”。

### 宿主 / smali 层

- 关闭在线 runtime 更新初始化（`JpApplication.onCreate` 中的 `sitzob.rpebal` 调用改为返回 null）。

  否则服务端推送一个更高版本的签名 runtime 时，会把打过补丁的 web bundle 覆盖回原版。

没有做：

- 解锁付费内容。
- 绕过登录。
- 绕过会员校验。
- 修改业务数据。
- 修改服务端协议。
- 传播或再分发。

## 签名

- 重新签名证书：`CN=jp-test`
- 证书 SHA-256：  
  `E9:AA:AA:81:4C:95:C4:B9:BD:A3:63:BC:53:48:7C:FD:AE:13:FC:57:16:53:81:2E:F8:54:76:2A:30:04:36:E8`
- 验证结果：v2 / v3 signature verified

## 安装注意

- 只能在隔离模拟器或测试机上安装。
- 先卸载原包：包名 `com.jp.app`。
- 签名不同，不能覆盖安装原版。
- 不能接收原厂更新。
- 不是完整安全保证，服务端仍可能返回其他非广告内容。

## 安装命令

```bash
adb uninstall com.jp.app || true
adb install -r -t /home/elin/Documents/Codex/2026-10-24/w-2/outputs/jp-host-release-modified-test.apk
```

## 已验证

- `apksig` 校验：v2 / v3 签名通过，无错误无警告。
- APK 内 `assets/web-bundle.zip` 的 SHA-256 与 `builtin-runtime.json` 记录一致。
- 交付的 APK 由 `reproduce-patched-apk.sh` 生成，脚本已端到端跑通。
- 补丁标记在打包后的 APK 内可复现。

## 未验证

- 未做真机 / 模拟器动态运行（本机 adb daemon 无法在沙箱内启动，Waydroid session 处于 STOPPED）。

## 复现脚本

`reproduce-patched-apk.sh` 是本改包使用的端到端复现脚本，输入原始 APK 即可复现签名后的测试包。

```bash
bash outputs/reproduce-patched-apk.sh /path/to/jp-host-release.apk /path/to/outdir
```

脚本内部会：解包 → 打补丁 → 重组 web bundle 并更新哈希 → apktool 回编 → apksig v2/v3 重新签名。

## 文件指纹

- APK SHA-256: `a7a9ed1729d8e4b3d2217c8d665116da183b55b17808c9c09666fe9ef950d87f`
- 原 APK SHA-256: `529671f4e6deb04a23ff1ec343ff7d49d67de364c0773a0a1d98077a0749e7b1`
