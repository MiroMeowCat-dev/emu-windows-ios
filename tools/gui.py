"""Windows desktop interface. Apple account credentials are never collected."""
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .common import BUILD, ROOT, WORKSPACE, UserError
from .source import preflight
from .windows import assemble, inspect_runtime, stage_resources


class WindowsApp:
    def __init__(self, window):
        self.window = window
        window.title("Emu · Windows 工具 0.2 预览版")
        window.geometry("900x700")
        window.minsize(820, 650)
        self.events = queue.Queue()
        self.busy = False
        bundled_runtime = WORKSPACE / "runtime/emu-ios-runtime.zip"
        self.runtime = tk.StringVar(value=str(bundled_runtime) if bundled_runtime.is_file() else "")
        self.game = tk.StringVar()
        self.output = tk.StringVar(value=str(BUILD / "windows"))
        self.bundle = tk.StringVar(value="local.emu.snowrunner")
        style = ttk.Style(window)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 7))
        body = ttk.Frame(window, padding=24)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="从 Windows 制作 iPhone 应用", font=("Microsoft YaHei UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="不需要自备 Mac · 先下载云端运行库，再在本地生成 IPA", foreground="#536071").grid(row=1, column=0, sticky="w", pady=(4, 14))
        notice = ("支持范围：原项目指定的 macOS ARM64 雪地奔驰 53.5（111）。\n"
                  "没有游戏也可以制作诊断 IPA，测试 SDL、Metal 和触控。Windows .exe 暂不支持。")
        ttk.Label(body, text=notice, justify="left").grid(row=2, column=0, sticky="w", pady=(0, 14))
        form = ttk.Frame(body)
        form.grid(row=3, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self.controls = []
        self.row(form, 0, "iOS 运行库", self.runtime, self.choose_runtime)
        self.row(form, 1, "游戏 .app（可选）", self.game, self.choose_game)
        self.row(form, 2, "输出文件夹", self.output, self.choose_output)
        ttk.Label(form, text="应用 Bundle ID").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=5)
        entry = ttk.Entry(form, textvariable=self.bundle)
        entry.grid(row=3, column=1, sticky="ew", pady=5)
        self.controls.append(entry)
        actions = ttk.Frame(body)
        actions.grid(row=4, column=0, sticky="ew", pady=(16, 8))
        self.runtime_button = self.button(actions, "校验运行库", self.check_runtime)
        self.check_button = self.button(actions, "制作诊断 IPA", lambda: self.package(False))
        self.game_button = self.button(actions, "制作游戏 IPA", lambda: self.package(True))
        self.resource_button = self.button(actions, "准备游戏资源", self.resources)
        self.preflight_button = self.button(actions, "检查游戏文件", self.check_game)
        self.state = tk.StringVar(value="已找到入门包内的运行库，可先校验或直接制作诊断 IPA。" if bundled_runtime.is_file()
                                  else "尚未选择运行库。先打开使用说明，完成一次云端构建。")
        ttk.Label(body, textvariable=self.state, wraplength=810).grid(row=5, column=0, sticky="w", pady=(0, 6))
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        self.log = tk.Text(body, height=12, wrap="word", font=("Microsoft YaHei UI", 10), bg="#f4f6f8", relief="flat", padx=12, pady=10)
        self.log.grid(row=7, column=0, sticky="nsew")
        body.rowconfigure(7, weight=1)
        self.log.configure(state="disabled")
        footer = ttk.Frame(body)
        footer.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(footer, text="使用说明 / 云端构建", command=self.help).pack(side="left", padx=(0, 8))
        ttk.Button(footer, text="打开输出目录", command=self.open_output).pack(side="left", padx=(0, 8))
        ttk.Button(footer, text="Sideloadly 官网", command=lambda: webbrowser.open("https://sideloadly.io/")).pack(side="left")
        ttk.Label(body, text="生成的 IPA 未签名。安装和签名在 Windows 侧载工具中完成；本工具不接收 Apple ID。",
                  foreground="#536071", wraplength=810).grid(row=9, column=0, sticky="w", pady=(10, 0))
        self.runtime.trace_add("write", self.refresh)
        self.game.trace_add("write", self.refresh)
        self.refresh()
        self.window.after(100, self.poll)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def row(self, parent, row, text, variable, browse):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        button = ttk.Button(parent, text="选择…", command=browse)
        button.grid(row=row, column=2, padx=(8, 0), pady=5)
        self.controls.extend([entry, button])

    def button(self, parent, label, action):
        button = ttk.Button(parent, text=label, command=action)
        button.pack(side="left", padx=(0, 8))
        self.controls.append(button)
        return button

    def refresh(self, *_):
        for control in self.controls:
            control.configure(state="disabled" if self.busy else "normal")
        if self.busy:
            return
        for button in [self.runtime_button, self.check_button]:
            button.configure(state="normal" if self.runtime.get().strip() else "disabled")
        self.game_button.configure(state="normal" if self.runtime.get().strip() and self.game.get().strip() else "disabled")
        for button in [self.resource_button, self.preflight_button]:
            button.configure(state="normal" if self.game.get().strip() else "disabled")

    def choose_runtime(self):
        path = filedialog.askopenfilename(title="选择 emu-ios-runtime.zip（需解开 GitHub 外层下载包）", filetypes=[("运行库 ZIP", "*.zip")])
        if path:
            self.runtime.set(path)

    def choose_game(self):
        path = filedialog.askdirectory(title="选择原始 SnowRunner.app 文件夹")
        if path:
            self.game.set(path)

    def choose_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output.set(path)

    def run(self, title, operation):
        if self.busy:
            return
        self.busy = True
        self.refresh()
        self.state.set(title)
        self.progress.start(12)

        def worker():
            try:
                result = operation(lambda text: self.events.put(("log", str(text))))
                self.events.put(("done", str(result or "操作完成")))
            except (UserError, OSError, ValueError) as error:
                self.events.put(("error", str(error)))
            except Exception as error:
                self.events.put(("error", "程序错误：" + repr(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", value + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
                if kind in {"done", "error"}:
                    self.busy = False
                    self.progress.stop()
                    self.refresh()
                    self.state.set(("完成：" if kind == "done" else "失败：") + value)
                    if kind == "error":
                        messagebox.showerror("Emu", value, parent=self.window)
        except queue.Empty:
            pass
        self.window.after(100, self.poll)

    def check_runtime(self):
        runtime = self.runtime.get().strip()
        self.run("正在校验运行库…", lambda progress: inspect_runtime(runtime, progress=progress) and "运行库校验通过")

    def package(self, with_game):
        runtime, game = self.runtime.get().strip(), self.game.get().strip() if with_game else None
        bundle = self.bundle.get().strip()
        output = Path(self.output.get().strip()) / ("SnowRunner-unsigned.ipa" if with_game else "EmuCheck-unsigned.ipa")
        self.run("正在制作 IPA…", lambda progress: assemble(runtime, output, game=game, bundle_id=bundle, progress=progress))

    def resources(self):
        game = self.game.get().strip()
        output = Path(self.output.get().strip()) / "SnowRunner.emuresources"
        self.run("正在校验并准备资源（约 52 GB，可重新运行续传）…", lambda progress: stage_resources(game, output, progress=progress))

    def check_game(self):
        game = self.game.get().strip()

        def check(progress):
            report = preflight(Path(game), full_resources=False, progress=progress)
            if not report["passed"]:
                raise UserError("\n".join(report["errors"][:10]))
            return "二进制校验和资源大小检查通过；资源准备时再校验全部资源内容。"
        self.run("正在检查游戏文件…", check)

    def help(self):
        path = ROOT / "docs/WINDOWS-zh.md"
        if os.name == "nt":
            os.startfile(path)
        else:
            webbrowser.open(path.as_uri())

    def open_output(self):
        path = Path(self.output.get().strip()).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(path)
            else:
                webbrowser.open(path.as_uri())
        except OSError as error:
            messagebox.showerror("Emu", str(error), parent=self.window)

    def close(self):
        if self.busy:
            messagebox.showinfo("Emu", "任务正在运行，请等待本次操作结束后关闭。", parent=self.window)
            return
        self.window.destroy()


def main():
    window = tk.Tk()
    WindowsApp(window)
    window.mainloop()
