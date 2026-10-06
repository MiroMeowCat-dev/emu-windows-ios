# emu 的能力边界与产品化路线

本说明基于仓库的 SnowRunner 示例实现。它处理的是 Steam 提供的 **macOS ARM64** 游戏库：校验固定版本、改写 Mach-O 加载元数据和少数指令、提供 iOS 侧适配层，再由 Xcode 构建和签名。它没有读取或运行 Windows PE 可执行文件，也没有 x86 指令转译器。

## 三个问题的结论

| 目标 | 目前原因 | 可行改进 |
| --- | --- | --- |
| 在 Windows 上完成全部流程 | 原 iOS 适配库编译依赖 Apple SDK，原签名和 USB 传输依赖 Mac 工具。 | 新版 `tools/windows.py` 在 Windows 完成 ARM64 提取、去签名、改写与 IPA 组装；中文 EXE 提供入口。公开 iOS 运行库由 GitHub macOS runner 编译一次。签名安装交给 Windows 侧载工具；资源通过 iPhone 文件夹导入。代码已经实现，本地组装测试通过，云端编译和实机路径待验证。 |
| 安装更简单 | 原流程需要依次执行 `setup`、`install`、`resources` 和 `launch`，首次复制约 52 GB。 | 当前增加 `./emu start` 串联步骤并沿用已有断点续传。`./emu package` 可导出已签名的本地 IPA 和 SHA-256 收据。首次安装后若系统要求信任开发者证书，按手机提示完成后重新运行 `start`；已完成的资源会跳过。 |
| 更多游戏、普通应用 | `data/supported-game.json` 固定 SnowRunner 53.5 (111) 的哈希和补丁地址；`app/Host/GameLauncher.m` 固定其资源路径、库、环境变量和 `main`；`app/Compat` 中的 SDL、触控和游戏状态逻辑也是专用的。 | 先支持更多 **原生 macOS ARM64** 应用：抽离每应用的描述文件、加载器、资源规则与输入适配。通用 AppKit 桌面 GUI 需要真正的窗口、事件、菜单、文件对话框等桥接；目前的缺失符号会主动停止程序，不能称为已支持。 |

## 推荐的下一阶段

1. **验证入口。** 保留固定哈希的安全门槛，增加版本报告和诊断包。对新游戏先检查 ARM64 切片、动态库依赖、图形 API、输入和资源布局；未知版本只报告，不自动改写。
2. **适配插件。** 定义应用描述文件，包括版本指纹、库映射、签名 ID、资源目录、入口点、补丁与前后哈希、输入方案。把 SnowRunner 的硬编码逐步移入一个插件；核心仅负责通用的复制、签名、安装、日志和回滚。
3. **用户界面与交付。** Windows 图形入口、本地组装与资源整理、手机“文件”目录导入和公开云端运行库构建已经编写。下一步实际执行云端构建，并在 iPhone 验证签名、诊断、资源导入和完整游戏。商业游戏内容保留在使用者本地。
4. **兼容性矩阵。** 每个应用和版本分别记录可启动、可交互、可保存、完整场景测试及所需设备。iPad、手柄、不同 iOS 版本和长期稳定性都要实机验证。

## Windows 游戏是另一条技术路线

Windows 游戏通常是 PE/x86 或 x86-64 程序。要在 iPhone 本机运行，需要 Windows API 层、CPU 指令模拟或转译、DirectX 图形转换、音频、输入、文件系统与安装器兼容，以及逐游戏的测试。即使构建出公共运行时，反作弊、驱动、DRM 和特殊图形功能仍会造成兼容差异。现有仓库的 Mach-O 重定向与 SnowRunner 适配层不能直接承担这些工作。Box64 项目面向 Linux ARM64；把它和 Wine 直接加进此 iOS 工程也不是可用的 Windows 游戏方案。

如果产品目标明确是“在 Windows 电脑上准备任意 Windows 游戏，再在 iPhone/iPad 本地运行”，应先做独立的技术验证：选一款无 DRM、无反作弊、低图形需求的游戏，分别证明 PE 启动、CPU 执行、Windows API、图形帧、输入、存档和设备签名。通过这些门槛后才适合设计通用安装器。

## 当前本地包的边界

`./emu package` 导出的 IPA 只包含应用和从用户自己的 SnowRunner 安装中准备的库，不含约 52 GB 的资源；资源仍由 `./emu resources` 送到已安装应用的数据容器。这样的分包可避免每次续签都重新复制大资源。IPA 内的开发签名受账号、设备和有效期限制，改变 Team ID 或 Bundle ID 会影响现有数据容器。导出包只应由其游戏所有者私下保存使用；公开发布需另行解决商业游戏内容授权、分发签名与商店审核等问题。

## 验证状态

Windows 源文件校验、结构测试 IPA 组装和资源整理使用真实的 Python 文件操作；测试覆盖去签名布局、跨平台源码契约、运行库损坏、路径越界、资源修复及失败时保留旧输出。Windows EXE 构建脚本执行真实程序的隐藏 GUI 启动检查。macOS 云端额外执行与 Apple `codesign` 的字节对比测试。目前没有真实游戏和可控 iPhone，**云端编译、真实游戏转换、安装与运行仍未验证**。详见 [Windows 使用说明](WINDOWS-zh.md)。

## 参考资料

- [本项目 README](https://github.com/brolnickij/emu)
- [Apple：Xcode 命令行工具](https://developer.apple.com/documentation/xcode/xcode-command-line-tool-reference)
- [Apple：在真机上构建和运行应用](https://developer.apple.com/documentation/xcode/building-and-running-an-app)
- [Apple：向已注册设备分发应用](https://developer.apple.com/documentation/xcode/distributing-your-app-to-registered-devices)
- [Box64 项目](https://github.com/ptitSeb/box64)
