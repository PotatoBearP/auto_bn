"""One explicitly selected skill probe; captures targeting and resulting state."""
import argparse
import time
import app
from paths import VALIDATION
import mouse_backend as mouse
from PIL import ImageGrab

def probe(skill,target,unit=None):
    h=app.find_game(); app.user32.SetForegroundWindow(h); time.sleep(1); box=app.bounds(h)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('Skill calibration requires approximately 1366x768.')
    def check():
        if app.user32.GetForegroundWindow()!=h or app.bounds(h)!=box:
            raise RuntimeError('Window or focus changed.')
    if unit:
        check(); mouse.click(box[0]+unit[0],box[1]+unit[1]); time.sleep(.6)
    check()
    ImageGrab.grab(bbox=box,all_screens=True).save(VALIDATION/f'skill-{skill}-before.png')
    source=(300,721) if skill==1 else (404,721)
    if skill==2:
        check(); mouse.click(box[0]+source[0],box[1]+source[1]); time.sleep(.5)
        ImageGrab.grab(bbox=box,all_screens=True).save(VALIDATION/f'skill-{skill}-selected.png')
        from combat import reticle_center,health_bars,skill_panel_visible,cooldown
        selected=ImageGrab.grab(bbox=box,all_screens=True)
        enemies=[b for b in health_bars(selected) if b['side']=='enemy']
        if not enemies: raise RuntimeError('没有可校准的敌方血条，请使用 combat.py。')
        origin=reticle_center(selected,enemies)
        mouse.drag((box[0]+origin[0],box[1]+origin[1]),(box[0]+target[0],box[1]+target[1]),check)
        preview=ImageGrab.grab(bbox=box,all_screens=True)
        preview.save(VALIDATION/f'skill-{skill}-preview.png')
        time.sleep(.4)
        preview=ImageGrab.grab(bbox=box,all_screens=True)
        center=reticle_center(preview,enemies)
        check(); mouse.click(box[0]+center[0],box[1]+center[1])
    else:
        mouse.click(box[0]+source[0],box[1]+source[1]); time.sleep(.5); check()
        mouse.move(box[0]+target[0],box[1]+target[1]); time.sleep(.3)
        ImageGrab.grab(bbox=box,all_screens=True).save(VALIDATION/f'skill-{skill}-preview.png')
        check(); mouse.click(box[0]+target[0],box[1]+target[1])
    time.sleep(3)
    ImageGrab.grab(bbox=box,all_screens=True).save(VALIDATION/f'skill-{skill}-after.png')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--skill',type=int,choices=(1,2),required=True)
    p.add_argument('--target',nargs=2,type=int,required=True); p.add_argument('--unit',nargs=2,type=int)
    a=p.parse_args(); probe(a.skill,a.target,a.unit)
