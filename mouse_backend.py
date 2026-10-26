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
    import app
    sx,sy=win32api.GetCursorPos()
    for step in range(1,9):
        control.check()
        app.move_cursor_input(round(sx+(x-sx)*step/8),round(sy+(y-sy)*step/8))
        time.sleep(.02)

def down():
    control.check()
    import app
    app.send_mouse(0x0002)

def scroll(delta):
    control.check()
    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL,0,0,int(delta),0)

def up():
    import app
    app.send_mouse(0x0004)

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
        import app
        for step in range(1,25):
            check();control.check()
            app.move_cursor_input(round(sx+(dx-sx)*step/24),round(sy+(dy-sy)*step/24))
            time.sleep(.025)
        time.sleep(.25)
    finally:
        up()
    return win32api.GetCursorPos()
