# Emu Windows 工具 0.2 预览版

这版把游戏二进制处理、IPA 组装和资源整理移到 Windows，并提供中文桌面界面。
使用者不需要自己的 Mac。iOS 原生运行库仍需在 GitHub 的 macOS 云端机器编译一次，下载后在 Windows 本地复用。

## 当前状态

| 功能 | 状态 |
| --- | --- |
| Windows x64 图形工具、无需安装 Python 的便携 EXE | 已实现；本地启动检查通过后才生成发布 ZIP |
| 原游戏 ARM64 提取、移除旧签名、平台和路径修改、指令补丁 | 已实现；原始文件与最终文件都必须匹配上游 SHA-256 |
| 无游戏的诊断 IPA、游戏 IPA 组装 | 已实现；使用结构测试文件验证过 Windows 组装流程 |
| 资源整理、全文件校验、重跑续传、损坏文件修复 | 已实现；小型资源测试通过，约 52 GB 实际资源尚未测试 |
| iPhone 内导入文件夹、校验资源、运行诊断、启动游戏 | 已编写；需要云端编译和实机验证 |
| 云端 iOS 运行库构建 | 已提供工作流；尚未在你的 GitHub 仓库运行 |
| Windows 签名和安装 | 交给侧载工具；未做实机验证，也未集成 Apple 登录 |
| Windows `.exe` / 任意游戏 / Windows 普通软件 | 不支持；原项目没有 Wine 或 x86 指令翻译层 |

工具不包含游戏文件，不需要你现在准备游戏，也不需要你把游戏上传到云端。
原项目支持的游戏是 **Steam macOS ARM64 SnowRunner 53.5（111）**。不是 Steam Windows 版。

## 1. 打开 Windows 工具

解压 `EmuWindows-portable.zip` 到有写入权限的目录（例如文档目录）。
打开 `EmuWindows/EmuWindows.exe`；保留旁边的 `_internal` 文件夹，不能只复制 EXE。
这是 Windows x64 便携版，没有安装程序和发行者签名。

源码方式需要 Python 3.10 或更新版本：双击项目中的 `emu-windows.cmd`。

## 2. 获得运行库：只需一次云端构建

将这份修改后的项目源码放入你有写权限的 GitHub 仓库。
只上传源码；不要上传 `build/`、游戏、个人配置、Apple 证书或密码。
可以 Fork 上游项目，然后将工具源码包里的文件放进 Fork。工具源码包也包含 `.github/workflows/windows-runtime.yml`。
GitHub 网页上传通常不方便保留隐藏目录，使用 Git 推送可保留 `.github` 工作流。

1. 仓库的 Actions 页面，选择 **Build Windows tool and public iOS runtime**。
2. 点击 **Run workflow**。
3. 等待 `ios-runtime` 任务成功。它下载已固定校验值的 SDL，编译公开代码，不需要 Apple ID、证书或游戏。
4. 下载 **emu-ios-runtime** artifact，解开 GitHub 外层下载 ZIP，得到 `emu-ios-runtime.zip`。
5. 在 Windows 工具的“iOS 运行库”栏选择这个文件，点击“校验运行库”。

运行库必须与 Windows 工具来自相同源码版本。工具会核对源码契约、全部文件 SHA-256、iOS 平台和 ARM64 架构。
这些校验保证文件完整和版本一致，不能证明第三方发布者可信；使用自己仓库构建的文件。
修改 iOS 或兼容层源码后需重新构建运行库。

工作流使用 GitHub 当前提供的 `xcode-27` ARM64 runner（公开预览）。运行库要求 SDK 27，因为上游已固定这个目标。
公开仓库的标准 runner 使用免费；私有仓库受账号分钟数和计费规则约束。
参考：[GitHub runner 文档](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

## 3. 现在没有游戏：先制作诊断 IPA

1. 选择通过校验的运行库，设置输出文件夹。
2. 点击“制作诊断 IPA”。输出 `EmuCheck-unsigned.ipa` 和校验回执 JSON。
3. 用 Windows 侧载工具签名安装 IPA。
4. 打开手机上的 **Emu Check**，点击 **Device check**。

诊断测试 SDL、Metal 和输入适配器，不包含游戏代码。自动输入检查不代表实际手指操作和完整游戏已经验证。
结果保存在应用 Documents 下的 `sdl-check.json`；可通过文件共享取回。
诊断包和游戏包默认使用同一个 Bundle ID，以后更新可沿用已有应用数据。

## 4. 在 Windows 签名安装

[Sideloadly 官方网站](https://sideloadly.io/)提供 Windows 版本。
按它的当前说明安装依赖、连接并信任 iPhone、导入 IPA，在侧载工具中登录并签名安装。
本工具不收集 Apple ID。iPhone 可能需要开启开发者模式；以系统提示及侧载工具说明为准。

输出 IPA 没有 Apple 开发签名和 provisioning profile，不能直接安装。
云端会给主可执行文件添加无需账号的 ad-hoc 签名，携带原项目的内存权限请求；该签名不能替代安装签名。
IPA 内 `Memory.entitlements` 及回执记录了所需的
`com.apple.developer.kernel.increased-memory-limit`。
实际签名工具是否保留、账号配置是否允许、设备是否受益，必须检查安装后结果；当前未验证。
没有这个权限时，诊断仍可能正常，但游戏可能因内存不足退出。

升级、续签和安装游戏包时使用相同 Bundle ID 和相同 Apple ID，覆盖更新之前先备份存档，勿删除旧应用。
参考：[Sideloadly 官方 FAQ](https://sideloadly.io/faq.html)。

## 5. 有游戏以后：处理游戏和资源

将你合法拥有的、指定版本的完整 macOS `.app` 文件夹放在 Windows 磁盘上。
选择 `.app` 文件夹，点击“检查游戏文件”，通过后点击“制作游戏 IPA”。
工具依次提取、验证和修改三个 ARM64 动态库；最终文件指纹必须与原项目提供的值完全一致，否则不输出新 IPA。
这一步无需 `lipo`、`codesign` 或 Xcode，也不会修改原始游戏。
当前还没有真实游戏文件来验证这条路径，云端测试会额外比较 Python 移除签名和 Apple `codesign` 的结果。

点击“准备游戏资源”，生成 `SnowRunner.emuresources` **文件夹**，不是压缩包。
会校验并复制约 52 GB 资源，只收集清单中的文件，不收集存档。
中断后重新运行会校验已完成文件并跳过，错误的文件会重做。需要输出盘留出足够空间。

将整个文件夹放到 iPhone“文件”可访问的位置，然后在安装好的游戏应用内：

1. 点击 **Import folder**，选择 `SnowRunner.emuresources` 文件夹。
2. 保持应用在前台，等待逐文件导入和 SHA-256 校验。
3. 完成后点击 **Start game**。已完成的文件可在重跑时恢复。

推荐使用外接 U 盘或移动硬盘，选择支持大文件的格式，例如 exFAT；部分 PAK 超过 FAT32 单文件上限。
手机需要约 52 GB 资源空间和运行余量。如果先把完整资源放到手机内部存储再导入，会同时占用两份空间。
Windows 文件整理和手机目录导入属于本版新增功能，USB、文件提供程序和 iOS 设备的实际行为仍需验证。

## 命令行（源码版）

```powershell
.\emu.cmd windows-runtime-check "D:\emu-ios-runtime.zip"
.\emu.cmd windows-build --runtime "D:\emu-ios-runtime.zip" --output "D:\output\EmuCheck-unsigned.ipa"
.\emu.cmd windows-build --runtime "D:\emu-ios-runtime.zip" --game "D:\SnowRunner.app" --output "D:\output\SnowRunner-unsigned.ipa"
.\emu.cmd windows-resources --game "D:\SnowRunner.app" --output "E:\SnowRunner.emuresources"
.\emu.cmd package-check "D:\output\SnowRunner-unsigned.ipa"
```

校验回执针对尚未签名的输出 IPA；经过侧载工具重新签名后，文件哈希会改变，不能继续使用这个回执验证。

## 开发者构建 Windows EXE

```powershell
python -m pip install --target build/packaging-deps pyinstaller==6.22.3
python -m unittest discover -s tests -v
python -m tools.freeze
```

输出 `build/releases/EmuWindows-portable.zip`。打包脚本会运行真实 EXE 的隐藏 GUI 启动检查，并验证内嵌资源版本一致。
构建日志：`build/logs/windows-freeze.log`；启动报告：`build/reports/windows-exe-smoke.json`。
