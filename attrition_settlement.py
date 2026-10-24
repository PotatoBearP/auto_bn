"""Confirm a variable result sequence and verify the next encounter is ready."""
import hashlib
import json
import time
from PIL import ImageGrab
import app
import combat
import control
import deployment
import mouse_backend as mouse
import settlement
from pvp import pass_available
from paths import COMBAT


def dialog_key(frame,stage,button):
    # Include panel contents to distinguish two successive dialogs with the
    # same title. Quantization reduces sensitivity to small rendering noise.
    # Use only the opaque dialog interior. Animated enemies behind its edges
    # must not keep resetting the stability timer forever.
    panel=frame.crop((535,275,820,430)).convert('L').resize((114,62))
    digest=hashlib.sha256(bytes(value//16 for value in panel.getdata())).hexdigest()
    return stage,tuple(button),digest


def ready_phase(frame):
    if settlement.map_visible(frame): return 'map'
    if deployment.start_button_visible(frame): return 'deployment'
    if combat.skill_panel_visible(frame) and pass_available(frame): return 'battle'
    return None


def finish_battle(next_battle=True,timeout=45):
    hwnd=app.find_game()
    if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
    app.focus_game(hwnd)
    box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('消耗战结算识别适用于约 1366×768。')
    def capture():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，消耗战结算已停止。')
        return ImageGrab.grab(bbox=box,all_screens=True)
    confirmed=[];events=[];pending=None;stable=None;stable_since=0
    ready_kind=None;ready_since=0;last_click=0;attempts=0
    deadline=time.monotonic()+timeout
    def complete(kind,frame):
        if pending: confirmed.append(pending[0])
        result={'confirmed':confirmed,'dialogs':events,'returned_to_map':kind=='map',
                'next_deployment_ready':kind=='deployment','next_battle_ready':kind=='battle'}
        frame.save(COMBAT/'settlement-next-battle.png')
        (COMBAT/'settlement-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    while time.monotonic()<deadline:
        frame=capture();stage,button=settlement.dialog(frame);now=time.monotonic()
        key=dialog_key(frame,stage,button) if stage and button else None
        if key and pending and key!=pending:
            confirmed.append(pending[0]);pending=None;attempts=0
        kind=None
        if key is None:
            kind=ready_phase(frame)
        if kind=='map' and next_battle:
            frame.save(COMBAT/'settlement-debug.png')
            raise RuntimeError('消耗战结算返回了地图，未检测到下一场。')
        if kind and (pending or confirmed) and (next_battle or kind=='map'):
            if kind!=ready_kind: ready_kind=kind;ready_since=now
            if now-ready_since>=.35: return complete(kind,frame)
        else: ready_kind=None
        if key!=stable: stable=key;stable_since=now
        if key and now-stable_since>=.25:
            if pending==key and now-last_click<1.2:
                time.sleep(.08);continue
            if attempts>=3:
                frame.save(COMBAT/'settlement-debug.png')
                raise RuntimeError('同一结算弹窗点击三次仍未切换，消耗战已停止。')
            fresh=capture();fresh_stage,fresh_button=settlement.dialog(fresh)
            if not fresh_button or dialog_key(fresh,fresh_stage,fresh_button)!=key: continue
            fresh.save(COMBAT/f'attrition-dialog-{len(events)+1}.png')
            control.check()
            left,top,right,bottom=button
            mouse.click(box[0]+(left+right)//2,box[1]+(top+bottom)//2)
            attempts+=1;pending=key;last_click=time.monotonic()
            events.append({'stage':stage,'button':list(button),'attempt':attempts})
        time.sleep(.08)
    frame=capture();frame.save(COMBAT/'settlement-debug.png')
    raise RuntimeError('等待消耗战结算或下一场超时。')
