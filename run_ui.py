import sys
import time
import webbrowser
import threading
import uvicorn

def open_browser():
    # Wait for the uvicorn server to start up before opening the browser
    # time.sleep(1.5)
    print("   Opening browser at http://127.0.0.1:8000 ...")
    # webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    print("=" * 60)
    print("   Starting Sentinel Geopolitical Intelligence UI")
    print("   Workspace URL: http://127.0.0.1:8000")
    print("=" * 60)

    # Launch browser thread
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        from src.web.app import app
        uvicorn.run(app, host="127.0.0.1", port=8000)
    except KeyboardInterrupt:
        print("\nStopping Sentinel UI...")
        sys.exit(0)
