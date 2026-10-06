# emu 本地增强版使用说明

**Windows 无自备 Mac 的新流程，请先看 [Windows 工具使用说明](WINDOWS-zh.md)。**
新版提供中文桌面工具、Windows 本地 IPA 组装、资源整理、手机文件夹导入入口和云端运行库构建。
下面保留的是原 Mac 流程，以及此前的检查命令；不是新版 Windows 工具的必需操作步骤。

本工具包包含源码、命令工具、适配元数据和说明，不包含游戏内容或可直接安装的游戏 IPA。当前仍只支持 SnowRunner 的 Steam macOS 53.5 (111)，build 25096372。游戏运行在 iPhone 上。下文的 Mac 工作流使用 Xcode 构建和签名；Windows 新版则使用云端公开运行库与本地组装。

## Windows 上先做准备

解压工具包，打开其 `emu-toolkit` 文件夹中的 PowerShell。需要 Python 3.10 或更高版本；`emu.cmd` 会使用系统中的 `python` 或 `py`。

1. 识别输入文件：

   ```powershell
   .\emu.cmd inspect "D:\Games\game.exe"
   ```

   Windows `.exe` 会被明确识别为当前运行时不支持。以下检查需要你自己的 **macOS 版本** `SnowRunner.app`；Windows 版本的游戏文件不能代替它。

2. 检查版本、三个 ARM64 库的哈希和全部资源的大小：

   ```powershell
   .\emu.cmd preflight --game "D:\Games\SnowRunner.app" --report ".\build\source-report.json"
   ```

3. 要确认资源内容也完整，执行完整 SHA-256 检查：

   ```powershell
   .\emu.cmd preflight --game "D:\Games\SnowRunner.app" --full --report ".\build\source-report-full.json"
   ```

   `--full` 会读取约 52 GB 数据，耗时取决于磁盘速度。检查不修改源游戏；报告应保存在游戏目录之外。任何失败都会返回非零退出码，报告中会保留各项问题。快速检查通过仅代表资源大小匹配，不能排除同大小的损坏文件。

如选择下面的 Mac 工作流，可把工具包、报告和你自己的 macOS 游戏副本放到可用的 Mac。报告方便排查问题，Mac 构建仍会重新校验真实输入，不会依赖报告跳过校验。没有 Mac 的用户使用 [Windows 新流程](WINDOWS-zh.md)。

## 在 Mac 上安装

Mac 需要 Xcode、有效的 Apple 开发签名账号以及受支持的游戏副本。通过 USB 连接 iPhone，完成信任此电脑和开发者模式设置；新复制资源需要约 52 GB 加额外空间。

```sh
chmod +x emu
./emu start --game "/path/to/SnowRunner.app"
```

首次运行会询问无法自动确定的签名信息。也可明确传入：

```sh
./emu start --game "/path/to/SnowRunner.app" --team YOURTEAMID --bundle-id dev.yourname.emu.snowrunner
```

`start` 依次设置、构建、安装、续传缺失资源并启动。若安装后 iOS 要求信任开发者证书，完成信任后重跑该命令。保留初次安装的 Team ID 和 Bundle ID，以便更新沿用原来的数据容器。

## 导出和核对安装包

在完成设置的 Mac 上执行：

```sh
./emu package
```

生成 `build/exports/SnowRunner.ipa` 和对应的 `SnowRunner.json` 校验收据。IPA 包含已准备的应用库，资源仍需要 `./emu resources` 单独传输；开发签名只适用于其配置允许的设备，并受有效期限制。

拿到 IPA 和 JSON 后，可在 Windows 检查是否完整：

```powershell
.\emu.cmd package-check ".\build\exports\SnowRunner.ipa"
```

这个检查验证 ZIP 结构、CRC、Bundle ID、程序入口名称以及整包 SHA-256。它不会确认 Apple 签名有效期、设备资格或游戏可运行性。

## 再次打包工具

```powershell
.\emu.cmd toolkit
```

生成 `build/releases/emu-toolkit.zip`。包内包含逐文件 SHA-256 清单，只收集指定的源码与元数据；`build/`、本地账号配置、签名证书和游戏内容不会被收集。

## 当前验证范围

Windows 上的源文件校验、归档核对和工具包生成可本地运行。ARM64 提取测试使用合成的 Mach-O 文件，IPA 导出中的 Apple 工具调用使用模拟测试。真实 Xcode 构建、签名、安装、iPhone/iPad 兼容性及游戏运行仍需要 Mac 和真机验证。
