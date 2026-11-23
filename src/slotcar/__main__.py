"""Entry point: ``python -m slotcar [--simulate]``."""

from __future__ import annotations

import argparse
import ctypes
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slotcar", description="Slot Car Duel - live BLE lap timing")
    parser.add_argument("--simulate", action="store_true",
                        help="start with the built-in track simulator connected (no hardware needed)")
    args = parser.parse_args(argv)

    if sys.platform == "win32":
        try:  # separate taskbar identity so our icon is used instead of python.exe's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SlotCarDuel.App.4")
        except Exception:
            pass

    from .ui.app import RaceApp

    app = RaceApp(simulate=args.simulate)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
