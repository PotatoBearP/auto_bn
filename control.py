"""Shared cancellation for one workflow, including a global Escape key."""
import threading
import win32api

stopped=threading.Event()

def reset():
    stopped.clear()

def stop():
    stopped.set()

def check():
    if stopped.is_set() or win32api.GetAsyncKeyState(0x1B)&0x8000:
        stopped.set()
        raise RuntimeError('已停止自动化。')
