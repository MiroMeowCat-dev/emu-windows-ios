# Emu Windows 0.2 预览版

## 推荐下载

下载 `EmuWindows-starter.zip`，解压后打开 `EmuWindows/EmuWindows.exe`。
包含中文 Windows x64 工具、匹配的公开 iOS 运行库、无游戏诊断 IPA 和使用说明，无需安装 Python 或自备 Mac。

现在没有游戏：可直接使用包内 `diagnostic/EmuCheck-unsigned.ipa`，或单独下载同名 IPA，在 Windows 侧载工具中签名安装，然后点击手机上的 **Device check**。

## 已验证

- 云端 Xcode 27 / iOS SDK 27 编译成功。
- macOS 49 项测试通过，包括 Python 去签名与 Apple codesign 的样本字节对比。
- Windows EXE 构建和隐藏 GUI 启动检查通过。
- 从 PATH 移除 Python，在中文目录下用真实 EXE 和真实运行库生成并校验诊断 IPA，通过。
- [三个构建任务均通过](https://github.com/MiroMeowCat-dev/emu-windows-ios/actions/runs/37399344715)，发布二进制对应提交 `356efec09e3ae973f031a981b141cb3b52a721ad`。

## 当前边界

这是准备和打包工具的 Windows 移植版。仅适配原项目指定的 **Steam macOS ARM64 SnowRunner 53.5（111）**，不支持 Windows .exe 或任意游戏/普通应用。

公开包没有游戏内容、Apple 密钥或安装签名。IPA 必须通过侧载工具签名。
真实游戏转换、手机侧载、内存权限、资源导入及游戏运行尚未实机验证。

[中文使用说明](https://github.com/MiroMeowCat-dev/emu-windows-ios/blob/main/docs/WINDOWS-zh.md) · [原项目](https://github.com/brolnickij/emu)

SHA-256:

```text
71840ee03b91644f04f7021b17ad75af3a112ecdaea20994b4516bbd99bb2a40  EmuWindows-starter.zip
5982c2c76babb4df127dca2336ca688614148e286ba8ac5d46517fa42f1bc0b3  EmuCheck-unsigned.ipa
```
