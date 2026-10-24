"""Reject two-or-more air units, strictly after entering each battle."""
import time
from collections import Counter
from functools import lru_cache
from PIL import Image,ImageChops,ImageStat,ImageGrab
import app
import attrition_vision
import combat
import control
import deployment
import formation
import mouse_backend as mouse
import settlement
from pvp import pass_available
from paths import COMBAT,TEMPLATES

FLAG_REGION=(24,108,89,175)
FLAG_POINT=(40,130)
RETREAT_POINT=(85,140)
CONFIRM_RETREAT_POINT=(670,555)


@lru_cache(maxsize=1)
def flag_reference():
    with Image.open(TEMPLATES/'attrition-white-flag.png') as image: return image.convert('RGB')


def flag_visible(frame):
    sample=frame.crop(FLAG_REGION).convert('RGB')
    return (sum(ImageStat.Stat(ImageChops.difference(sample,flag_reference())).mean)/3<18 or
            retreat_button_visible(frame))


@lru_cache(maxsize=3)
def retreat_reference(name):
    with Image.open(TEMPLATES/f'attrition-retreat-{name}.png') as image: return image.convert('RGB')


def retreat_matches(frame,name,region):
    crop=frame.crop(region).convert('RGB')
    return sum(ImageStat.Stat(ImageChops.difference(crop,retreat_reference(name))).mean)/3<12


def retreat_button_visible(frame):
    return retreat_matches(frame,'menu',(5,119,178,163))


def retreat_confirm_visible(frame):
    return (retreat_matches(frame,'title',(630,198,726,235)) and
            retreat_matches(frame,'button',(620,535,721,575)))


def battle_ready(frame):
    return (not retreat_confirm_visible(frame) and
            not deployment.start_button_visible(frame) and pass_available(frame) and
            combat.skill_panel_visible(frame) and flag_visible(frame) and settlement.phase(frame) is None)


def wait_for(capture,predicate,timeout,message):
    deadline=time.monotonic()+timeout;since=None
    while time.monotonic()<deadline:
        frame=capture()
        if predicate(frame):
            if since is None: since=time.monotonic()
            if time.monotonic()-since>=.35: return frame
        else: since=None
        time.sleep(.1)
    frame=capture();frame.save(COMBAT/'attrition-opening-debug.png')
    raise RuntimeError(message)


def scan_air(capture,first,samples=8):
    votes=Counter(attrition_vision.air_cells(first))
    for _ in range(samples):
        time.sleep(.12)
        votes.update(set(attrition_vision.air_cells(capture())))
        # Confirm each coordinate on separate frames; never count the same
        # flapping unit twice, and tolerate different units matching in
        # different animation frames.
        confirmed=sorted(cell for cell,count in votes.items() if count>=2)
        if len(confirmed)>=2: return confirmed
    return sorted(cell for cell,count in votes.items() if count>=2)


def wait_restart(capture):
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        frame=capture()
        if settlement.phase(frame) in ('loot','experience'):
            result=settlement.finish_battle(next_battle=True)
            frame=capture()
            return frame,result
        if deployment.start_button_visible(frame):
            frame=wait_for(capture,deployment.start_button_visible,10,'重开布阵界面未稳定。')
            return frame,{'next_deployment_ready':True}
        time.sleep(.1)
    capture().save(COMBAT/'attrition-opening-debug.png')
    raise RuntimeError('点击白旗放弃后未出现结算或布阵，未重复点击。')


def prepare(opening_frame,progress=lambda text:None,max_rerolls=25):
    """Called only after Start; every reroll also starts before touching the flag."""
    hwnd=app.find_game();box=app.bounds(hwnd)
    def capture():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，消耗战开局筛选已停止。')
        return ImageGrab.grab(bbox=box,all_screens=True)
    checks=[];rerolls=[]
    while True:
        cells=scan_air(capture,opening_frame)
        checks.append({'air_count':len(cells),'air_cells':[list(cell) for cell in cells]})
        if len(cells)<2: return {'checks':checks,'rerolls':rerolls,'accepted':True}
        if len(rerolls)>=max_rerolls:
            raise RuntimeError('连续重开阵容达到上限，消耗战已停止。')
        progress(f'开局有 {len(cells)} 个飞行怪；确认进入战斗后点击白旗重开阵容。')
        wait_for(capture,battle_ready,30,'未确认进入真实战斗，未点击白旗。')
        fresh=capture()
        if not battle_ready(fresh): continue
        fresh.save(COMBAT/f'attrition-reroll-{len(rerolls)+1}-battle.png')
        if not retreat_button_visible(fresh):
            control.check();mouse.click(box[0]+FLAG_POINT[0],box[1]+FLAG_POINT[1])
        wait_for(capture,retreat_button_visible,5,'白旗未展开撤退按钮，未重复点击。')
        if not retreat_button_visible(capture()): raise RuntimeError('撤退菜单已改变，未点击。')
        mouse.click(box[0]+RETREAT_POINT[0],box[1]+RETREAT_POINT[1])
        wait_for(capture,retreat_confirm_visible,5,'未识别撤退确认弹窗，未确认。')
        if not retreat_confirm_visible(capture()): raise RuntimeError('撤退确认界面改变，未确认。')
        mouse.click(box[0]+CONFIRM_RETREAT_POINT[0],box[1]+CONFIRM_RETREAT_POINT[1])
        next_frame,result=wait_restart(capture)
        next_frame.save(COMBAT/f'attrition-reroll-{len(rerolls)+1}-deployment.png')
        rerolls.append({'air_count':len(cells),'entered_battle':True,'flag_clicked':True,'retreat_confirmed':True,
                        'settlement':result})
        # A new lineup can still be bad. It must enter battle before its flag
        # can be clicked, exactly like the first lineup.
        opening_frame=next_frame
        if result.get('next_deployment_ready'):
            deployment.start_battle(formation.active(),verify_placement=False)
        elif not result.get('next_battle_ready'):
            raise RuntimeError('白旗重开后未确认下一场就绪。')
