"""
체크밸브 작업지도서 런처
- 더블클릭(또는 exe 실행) 시 같은 폴더의 check_valve.html 을 기본 브라우저로 열어
  웹 작업지도서 UI(영상 재생 포함)를 띄운다.
- exe(PyInstaller) 와 .py 양쪽에서 동작하도록 실행 위치를 자동 판별한다.
"""
import os
import sys
import webbrowser


def base_dir() -> str:
    # PyInstaller 로 빌드된 exe 는 sys.frozen 이 True. 이때 exe 가 있는 폴더 기준.
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    html_path = os.path.join(base_dir(), "check_valve.html")

    if not os.path.exists(html_path):
        # 콘솔이 없을 수 있으므로 메시지 박스로 안내
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "check_valve.html 을 찾을 수 없습니다.\n"
                "exe 와 같은 폴더에 check_valve.html, mp4 가 함께 있어야 합니다.",
                "체크밸브 작업지도서",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            print("check_valve.html not found:", html_path)
        return

    url = "file:///" + html_path.replace("\\", "/")
    webbrowser.open(url)


if __name__ == "__main__":
    main()
