"""Windows mouse events following KeymouseGo v5.2.1's API sequence.

Reference: https://github.com/taojy123/KeymouseGo/blob/v5.2.1/Event/WindowsEvents.py
This is an independent, minimal implementation; no upstream code is bundled.
"""
import time
import win32api
import win32con
import control

def move(x, y):
    control.check()
    if win32api.GetSystemMetrics(win32con.SM_CMONITORS) > 1:
        win32api.SetCursorPos((int(x),int(y)))
    else:
        width,height=win32api.GetSystemMetrics(0),win32api.GetSystemMetrics(1)
        win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE|win32con.MOUSEEVENTF_MOVE,
                             int(x*65535/width),int(y*65535/height),0,0)

def down():
    control.check()
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,0,0,0,0)

def scroll(delta):
    control.check()
    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL,0,0,int(delta),0)

def up():
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,0,0,0,0)

def click(x,y):
    move(x,y); time.sleep(.3); down()
    try:
        time.sleep(.15)
    finally:
        up()

def drag(source,destination,check=lambda:None):
    sx,sy=source; dx,dy=destination
    check(); move(sx,sy); time.sleep(.35); check(); down()
    try:
        time.sleep(.15)
        check(); move(dx,dy)
        time.sleep(.25)
    finally:
        up()
    return win32api.GetCursorPos()
