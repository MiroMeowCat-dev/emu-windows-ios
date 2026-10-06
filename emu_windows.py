"""Source and frozen Windows desktop entry point."""
import sys


def main():
    if "--smoke-report" in sys.argv:
        from pathlib import Path
        import tkinter as tk
        from tools.common import ROOT, write_json
        from tools.gui import WindowsApp
        from tools.windows import contract_key
        from tools.resources import manifest_files
        path = Path(sys.argv[sys.argv.index("--smoke-report") + 1]).resolve()
        window = tk.Tk()
        window.withdraw()
        app = WindowsApp(window)
        window.update_idletasks()
        report = {"frozen": bool(getattr(sys, "frozen", False)), "gui_initialized": True,
                  "contract_key": contract_key(), "resource_files": len(manifest_files()),
                  "bundled_help": (ROOT / "docs/WINDOWS-zh.md").is_file(),
                  "game_action_disabled_without_files": str(app.game_button.cget("state")) == "disabled",
                  "runtime_action_disabled_without_runtime": str(app.check_button.cget("state")) == "disabled"}
        write_json(path, report)
        window.destroy()
    elif "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from tools.cli import main as cli_main
        cli_main()
    else:
        from tools.gui import main as gui_main
        gui_main()


if __name__ == "__main__":
    main()
