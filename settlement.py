"""Confirm the two calibrated victory dialogs, then observe the world map."""
import json
import time
from functools import lru_cache
from PIL import Image, ImageGrab, ImageChops, ImageStat
import app
import mouse_backend as mouse
from paths import COMBAT, TEMPLATES
import control
from target_priority import ATTRITION

REGIONS={
    'loot-title':(620,216,730,251), 'loot-confirm':(726,495,946,537),
    'experience-title':(620,232,732,274), 'experience-confirm':(726,474,946,516),
    'experience-confirm-alt':(726,474,946,516),
    'world-map-title':(1120,20,1295,67),
    'sweep-loot-title':(620,216,730,251), 'sweep-loot-confirm':(806,495,946,537),
    'attrition-score-title':(610,195,750,234), 'attrition-score-confirm':(756,535,890,575),
}

@lru_cache(maxsize=8)
def reference_image(name):
    with Image.open(TEMPLATES/(name+'.png')) as image:
        return image.convert('RGB')

def matches(image,name):
    reference=reference_image(name)
    crop=image.crop(REGIONS[name]).convert('RGB')
    return sum(ImageStat.Stat(ImageChops.difference(crop,reference)).mean)/3<10

@lru_cache(maxsize=1)
def map_title_features():
    reference=reference_image('world-map-title')
    white=[];background=[]
    for y in range(0,reference.height,2):
        for x in range(0,reference.width,2):
            r,g,b=reference.getpixel((x,y))
            if min(r,g,b)>210 and max(r,g,b)-min(r,g,b)<30: white.append((x,y))
            elif max(r,g,b)<145: background.append((x,y))
    return white,background

def map_visible(image):
    if matches(image,'world-map-title'): return True
    white,background=map_title_features()
    if not white: return False
    pixels=image.convert('RGB').load();left,top,right,bottom=REGIONS['world-map-title']
    for dy in range(-12,13,2):
        for dx in range(-12,13,2):
            if left+dx<0 or top+dy<0 or right+dx>image.width or bottom+dy>image.height: continue
            def is_white(x,y):
                color=pixels[left+dx+x,top+dy+y]
                return min(color)>190 and max(color)-min(color)<40
            positive=sum(is_white(x,y) for x,y in white)/len(white)
            if positive<.88: continue
            # Require the spaces around the glyphs to remain dark, avoiding
            # snowy map terrain or a uniformly white loading screen.
            negative=sum(max(pixels[left+dx+x,top+dy+y])<180 for x,y in background)/max(1,len(background))
            if negative>.85: return True
    return False

def locate_region(image,name,low,high):
    left,top,right,bottom=REGIONS[name]
    if matches(image,name): return REGIONS[name]
    reference=reference_image(name)
    small=reference.resize((max(1,reference.width//3),max(1,reference.height//3)))
    for y in range(low,min(high,image.height-reference.height)+1,2):
        crop=image.crop((left,y,right,y+reference.height)).convert('RGB')
        quick=sum(ImageStat.Stat(ImageChops.difference(crop.resize(small.size),small)).mean)/3
        if quick>14: continue
        score=sum(ImageStat.Stat(ImageChops.difference(crop,reference)).mean)/3
        if score<10: return (left,y,right,y+reference.height)
    return None

@lru_cache(maxsize=8)
def experience_title_text(pixels,size):
    path=COMBAT/'settlement-title-ocr.png'
    mask=Image.frombytes('L',size,pixels)
    mask.resize((size[0]*2,size[1]*2)).save(path)
    return ''.join(word['Text'] for word in app.recognize(path,'zh-Hans-CN',True))

def dialog(image):
    title=locate_region(image,'experience-title',100,400)
    if title:
        button=locate_region(image,'experience-confirm-alt',360,650)
        if button: return 'experience',button
    for stage in ('loot','experience'):
        title=locate_region(image,stage+'-title',100,400)
        if title:
            button=locate_region(image,stage+'-confirm',360,650)
            if button: return stage,button
    if ATTRITION.get():
        title=locate_region(image,'attrition-score-title',100,400)
        if title:
            button=locate_region(image,'attrition-score-confirm',400,650)
            if button: return 'loot',button
        from pvp import result_dialog
        outcome,button=result_dialog(image)
        if outcome and button:
            x,y=button
            return 'loot',(x-2,y-2,x+2,y+2)
    title=locate_region(image,'sweep-loot-title',100,400)
    if title:
        button=locate_region(image,'sweep-loot-confirm',360,650)
        if button: return 'loot',button
    # Victory and XP headings vary; require a known confirm button plus OCR.
    for stage in ('loot','experience'):
        button=locate_region(image,stage+'-confirm',360,650)
        if not button and stage=='experience':
            button=locate_region(image,'experience-confirm-alt',360,650)
        if not button: continue
        crop=image.crop((500,100,850,min(400,button[1]-50))).convert('RGB')
        mask=Image.new('L',crop.size)
        mask.putdata([0 if r>180 and g>100 and b<100 and r>g*1.05 else 255
                      for r,g,b in crop.getdata()])
        text=experience_title_text(mask.tobytes(),mask.size)
        if stage=='loot' and any(title in text for title in ('战胜','胜利','战利品')):
            return stage,button
        if stage=='experience' and ('经验' in text or '技能点数' in text):
            return stage,button
    return None,None

def phase(image):
    stage,_=dialog(image)
    if stage: return stage
    if map_visible(image): return 'map'
    return None

def finish_battle(next_battle=False):
    if ATTRITION.get():
        from attrition_settlement import finish_battle as finish_attrition
        return finish_attrition(next_battle=next_battle)
    hwnd=app.find_game()
    if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
    app.focus_game(hwnd)
    box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('结算识别适用于约 1366×768。')
    def capture():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，停止结算点击。')
        return ImageGrab.grab(bbox=box,all_screens=True)
    clicked=[];deadline=time.monotonic()+30
    pending=None;attempts={};last_click=0;stable_stage=None;stable_since=0;map_since=None
    battle_since=None
    while time.monotonic()<deadline:
        frame=capture();stage,button=dialog(frame)
        now=time.monotonic()
        if stage is None and map_visible(frame): stage='map'
        if next_battle:
            from deployment import start_button_visible
            retained_deployment=start_button_visible(frame) if stage is None else False
            ready=(stage is None and retained_deployment and 'loot' in clicked and
                   (pending=='experience' or 'experience' in clicked))
            if ready:
                if battle_since is None: battle_since=now
                if now-battle_since>=.35:
                    if pending: clicked.append(pending)
                    frame.save(COMBAT/'settlement-next-battle.png')
                    result={'confirmed':clicked,'returned_to_map':False,
                            'next_battle_ready':not retained_deployment,
                            'next_deployment_ready':retained_deployment}
                    (COMBAT/'settlement-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                    return result
            else: battle_since=None
        if pending and stage in ('loot','experience','map') and stage!=pending:
            clicked.append(pending);pending=None
        if stage=='map':
            if next_battle:
                raise RuntimeError('扫荡结算后返回了地图，未检测到下一场；未搜索或重新布阵。')
            if map_since is None: map_since=now
            if now-map_since<.35:
                time.sleep(.08);continue
            frame.save(COMBAT/'settlement-map.png')
            result={'confirmed':clicked,'returned_to_map':True}
            (COMBAT/'settlement-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            return result
        map_since=None
        if stage!=stable_stage:
            stable_stage=stage;stable_since=now
        if stage in ('loot','experience') and stage not in clicked and now-stable_since>=.25:
            if pending==stage and now-last_click<1.2:
                time.sleep(.08);continue
            if attempts.get(stage,0)>=3:
                frame.save(COMBAT/'settlement-debug.png')
                raise RuntimeError('结算确定点击三次后界面仍未切换，已停止。')
            # Both dialog title and button must still match immediately before input.
            fresh_stage,fresh_button=dialog(capture())
            if fresh_stage!=stage or fresh_button!=button: continue
            frame.save(COMBAT/f'settlement-{stage}.png')
            left,top,right,bottom=button
            mouse.click(box[0]+(left+right)//2,box[1]+(top+bottom)//2)
            pending=stage;attempts[stage]=attempts.get(stage,0)+1;last_click=time.monotonic()
            time.sleep(.12)
        else: time.sleep(.08)
    frame.save(COMBAT/'settlement-debug.png')
    raise RuntimeError('等待结算界面或返回地图超时，已保存 settlement-debug.png。')

if __name__=='__main__':
    print(json.dumps(finish_battle(),ensure_ascii=True))
