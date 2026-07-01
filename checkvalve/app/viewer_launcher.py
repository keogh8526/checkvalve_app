"""Tiny viewer packaged inside every export zip — opens the sibling index.html via
file:// (no server needed). Generalizes check_valve_app/launcher.py to index.html."""
import os
import sys
import webbrowser


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    html = os.path.join(base_dir(), "index.html")
    if not os.path.exists(html):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "index.html 을 찾을 수 없습니다.\n같은 폴더에 함께 두세요.",
                                             "체크밸브 작업지도서", 0x10)
        except Exception:
            print("index.html not found:", html)
        return
    webbrowser.open("file:///" + html.replace("\\", "/"))


if __name__ == "__main__":
    main()
