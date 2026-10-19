"""Ranked PVP deployment, opening sweep, passing, and settlement loops."""
import json
import time
import re
from functools import lru_cache
from PIL import Image,ImageGrab,ImageChops,ImageStat
import app
import control
import mouse_backend as mouse
import deployment
import combat
from unit_ai import get as unit_ai
from paths import ARTIFACTS,TEMPLATES
from recognition import retry_observation

ROOT=ARTIFACTS/'runtime'/'pvp'
ROOT.mkdir(parents=True,exist_ok=True)
class DeploymentSettled(RuntimeError):
    def __init__(self,outcome):
        self.outcome=outcome
        super().__init__('部署期间已进入结算。')

def deployment_io(capture,click):
    def guarded_capture():
        frame=capture();current=stage(frame)
        if current in ('victory','defeat','settlement'): raise DeploymentSettled(current)
        return frame
    def guarded_click(point):
        guarded_capture()
        click(point)
    return guarded_capture,guarded_click
REGIONS={'entry':(791,679,872,765),'title':(350,156,444,204),
         'start':(999,508,1111,575),'matching':(420,40,646,84),
         'defeat':(620,216,730,251),'confirm':(726,495,946,537)}

@lru_cache(maxsize=6)
def reference(name):
    with Image.open(TEMPLATES/('pvp-'+name+'.png')) as source:
        return source.convert('RGB')

def matches(image,name):
    crop=image.crop(REGIONS[name]).convert('RGB')
    return sum(ImageStat.Stat(ImageChops.difference(crop,reference(name))).mean)/3<12


def ranked_visible(image):
    # Fixed dialog controls can shift by a few pixels with client sizing.
    rgb=image.convert('RGB')
    for name in ('title','start'):
        left,top,right,bottom=REGIONS[name]
        template=reference(name)
        found=False
        for dy in range(-4,5):
            for dx in range(-4,5):
                crop=rgb.crop((left+dx,top+dy,right+dx,bottom+dy))
                if sum(ImageStat.Stat(ImageChops.difference(crop,template)).mean)/3<12:
                    found=True;break
            if found: break
        if not found: return False
    return True

@lru_cache(maxsize=1)
def matching_letters():
    banner=reference('matching')
    return [(x,y) for y in range(0,banner.height,3) for x in range(0,banner.width,3)
            if min(banner.getpixel((x,y)))>215]

def matching_banner(image):
    # Match white lettering rather than the map underneath the translucent UI.
    pixels=image.convert('RGB').load();letters=matching_letters()
    for dy in range(-4,5,2):
        for dx in range(-4,5,2):
            white=sum(min(pixels[420+x+dx,40+y+dy])>210 for x,y in letters)
            if white/max(1,len(letters))>.84: return True
    return False

def entry_visible(image):
    template=reference('entry');pixels=image.convert('RGB').load()
    marks=[(x,y) for y in range(65,84) for x in range(20,63)
           if min(template.getpixel((x,y)))>215]
    if not marks: return False
    def green(color):
        r,g,b=color
        return g>90 and g>r*1.3 and g>b*1.3
    icon=[(x,y) for y in range(5,63,2) for x in range(10,72,2)
          if green(template.getpixel((x,y)))]
    if not icon: return False
    # Transparent button backgrounds vary; match the foreground at a shared
    # offset so one-pixel UI shifts do not destroy the narrow letter mask.
    for dy in range(-2,3):
        for dx in range(-3,4):
            white=sum(min(pixels[791+x+dx,679+y+dy])>190 for x,y in marks)
            if white/len(marks)<.8: continue
            matched=sum(green(pixels[791+x+dx,679+y+dy]) for x,y in icon)
            if matched/len(icon)>.8: return True
    return False

def result_button(image):
    pixels=image.convert('RGB').load();runs=[]
    for y in range(430,min(620,image.height),2):
        left=None
        for x in range(700,min(990,image.width)):
            r,g,b=pixels[x,y];orange=r>170 and 80<g<205 and b<120 and r-g>35
            if orange and left is None: left=x
            if left is not None and (not orange or x==min(990,image.width)-1):
                if x-left>=60: runs.append((left,y,x))
                left=None
    groups=[]
    for run in runs:
        # White button lettering interrupts the orange run for up to 24 pixels.
        if not groups or run[1]-groups[-1][-1][1]>28: groups.append([])
        groups[-1].append(run)
    groups=[group for group in groups if 16<=group[-1][1]-group[0][1]<=80]
    if not groups: return None
    group=max(groups,key=lambda group:sum(right-left for left,y,right in group))
    left=min(x for x,y,right in group);right=max(right for x,y,right in group)
    return ((left+right)//2,(group[0][1]+group[-1][1])//2)

@lru_cache(maxsize=2)
def result_title_mask(outcome):
    title=reference(outcome)
    return {(x,y) for y in range(0,title.height,2) for x in range(0,title.width,2)
            if is_title_gold(title.getpixel((x,y)))}

def is_title_gold(color):
    r,g,b=color
    return r>175 and g>100 and b<105 and r-g>25

def result_dialog(image):
    rgb=image.convert('RGB');pixels=rgb.load()
    dark=sum(max(color)<120 and max(color)-min(color)<30
             for color in rgb.crop((440,218,600,244)).getdata())
    if dark<2500: return None,None
    # Fast rejection keeps regular deployment/combat polling inexpensive.
    title_gold=sum(is_title_gold(color) for color in rgb.crop((604,190,748,278)).getdata())
    if title_gold<45: return None,None
    best=(0,None)
    for dy in range(-24,25):
        for dx in range(-8,9):
            actual={(x,y) for y in range(0,35,2) for x in range(0,110,2)
                    if is_title_gold(pixels[620+dx+x,216+dy+y])}
            if len(actual)<15: continue
            for outcome in ('defeat','victory'):
                expected=result_title_mask(outcome)
                score=len(actual & expected)/max(1,len(actual | expected))
                if score>best[0]: best=(score,outcome)
    button=result_button(rgb)
    if best[0]>.72: return best[1],button
    # Shared result panel + orange confirmation are sufficient to settle even
    # if font rendering makes the exact win/loss word temporarily ambiguous.
    if button and dark>2500: return 'settlement',button
    return None,None

def stage(image,allow_deployment=False):
    outcome,_=result_dialog(image)
    if outcome: return outcome
    if matching_banner(image): return 'matching'
    if ranked_visible(image): return 'ranked'
    if matches(image,'entry') or entry_visible(image): return 'map'
    timer=list(image.crop((628,2,738,63)).convert('RGB').getdata())
    timer_orange=sum(r>170 and 40<g<150 and b<75 and r>g*1.4 for r,g,b in timer)
    timer_green=sum(g>70 and g>r*1.3 and g>b*1.3 for r,g,b in timer)
    opponent=image.crop((1120,14,1285,40)).convert('RGB').getdata()
    opponent_gold=sum(r>200 and g>130 and b<100 for r,g,b in opponent)
    if max(timer_orange,timer_green)>250 and opponent_gold>20:
        try:
            start_button(image)
            return 'deployment'
        except RuntimeError:
            pass
        return 'battle'
    return None

def wait_start_stage(capture,timeout=8,allow_started=False):
    """Allow focus/return-to-base rendering to finish before rejecting entry."""
    deadline=time.monotonic()+timeout
    accepted=('map','ranked')
    if allow_started: accepted+=('matching','deployment','battle','victory','defeat','settlement')
    while True:
        frame=capture();current=stage(frame)
        if current in accepted: return frame,current
        if current in ('matching','deployment','battle','victory','defeat','settlement'):
            frame.save(ROOT/'start-unrecognized.png')
            raise RuntimeError('当前仍在 PVP 对局或结算中，请返回基地后启动。')
        if time.monotonic()>=deadline:
            frame.save(ROOT/'start-unrecognized.png')
            raise RuntimeError('等待 8 秒后仍未识别基地 PVP 入口，已保存 start-unrecognized.png。')
        time.sleep(.15)


def monitor_match(capture,progress=lambda text:None,timeout=300):
    deadline=time.monotonic()+timeout
    observations=[]
    next_check=time.monotonic()+4
    while time.monotonic()<deadline:
        # Short sleeps keep Esc/Stop responsive between the four-second polls.
        while time.monotonic()<next_check:
            control.check()
            time.sleep(min(.1,max(0,next_check-time.monotonic())))
        frame=capture();current=stage(frame,allow_deployment=True)
        observations.append({'state':current or 'transition'})
        frame.save(ROOT/'after.png')
        progress({'matching':'PVP 正在寻找对局，4 秒后再次检查…',
                  'deployment':'PVP 已进入布置界面。','battle':'PVP 已进入战斗。'}.get(
                      current,'PVP 界面切换中，4 秒后再次检查…'))
        if current in ('deployment','battle','defeat','victory','settlement'): return frame,current,observations
        if current in ('map','ranked'):
            raise RuntimeError('PVP 匹配已返回地图或排位赛面板，未重复开战。')
        next_check=time.monotonic()+4
    raise RuntimeError('PVP 状态监测超过 5 分钟，已停止；未取消或重复匹配。')

def start_match(progress=lambda text:None):
    control.check();hwnd=app.find_game()
    if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
    app.focus_game(hwnd);box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('PVP 匹配校准适用于约 1366×768。')
    def capture():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，停止 PVP 操作。')
        return ImageGrab.grab(bbox=box,all_screens=True)
    def click(point):
        capture()
        mouse.click(box[0]+point[0],box[1]+point[1])
    frame,current=wait_start_stage(capture,allow_started=True)
    report={'clicked_pvp':False,'clicked_start':False}
    if current in ('matching','deployment','battle','victory','defeat','settlement'):
        report.update(status=current,already_started=True)
    else:
        if current=='map':
            progress('正在打开 PVP 排位赛…')
            click((832,722));report['clicked_pvp']=True
            deadline=time.monotonic()+8
            retry_at=time.monotonic()+2;entry_attempts=1
            while True:
                frame=capture();current=stage(frame)
                if current=='ranked': break
                if current in ('matching','deployment','battle','victory','defeat','settlement'):
                    report.update(status=current,already_started=True)
                    break
                now=time.monotonic()
                if now>=deadline:
                    frame.save(ROOT/'ranked-unrecognized.png')
                    raise RuntimeError('等待 PVP 排位赛面板超时，已保存 ranked-unrecognized.png，未点击开战。')
                if current=='map' and entry_attempts<3 and now>=retry_at:
                    # Retry only an entry still positively visible on the base.
                    click((832,722));entry_attempts+=1;retry_at=now+2
                time.sleep(.08)
            report['entry_attempts']=entry_attempts
        if current in ('matching','deployment','battle','victory','defeat','settlement'):
            if current=='matching':
                frame,current,observations=monitor_match(capture,progress)
                report.update(status=current,observations=observations,poll_interval=4)
            frame.save(ROOT/'after.png')
            (ROOT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            return report
        if current!='ranked': raise RuntimeError('未确认 PVP 入口或排位赛面板，未开始匹配。')
        if stage(capture())!='ranked': raise RuntimeError('PVP 面板改变，未点击开战。')
        frame.save(ROOT/'before.png')
        progress('正在点击 PVP 开战，等待匹配…')
        click((1054,541));report['clicked_start']=True
        deadline=time.monotonic()+12
        while True:
            frame=capture();current=stage(frame,allow_deployment=True)
            if current in ('matching','deployment','battle','defeat','victory','settlement'):
                report['status']=current;break
            if time.monotonic()>=deadline:
                frame.save(ROOT/'after.png')
                raise RuntimeError('已点击一次 PVP 开战，尚未确认匹配；未重复点击。')
            time.sleep(.08)
    if report['status']=='matching':
        progress('匹配已启动，每 4 秒检查一次状态…')
        frame,current,observations=monitor_match(capture,progress)
        report.update(status=current,observations=observations,poll_interval=4)
    frame.save(ROOT/'after.png')
    (ROOT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def game_capture():
    hwnd=app.find_game();app.focus_game(hwnd);box=app.bounds(hwnd)
    def capture():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，停止 PVP 循环。')
        return ImageGrab.grab(bbox=box,all_screens=True)
    def click(point):
        capture();mouse.click(box[0]+point[0],box[1]+point[1])
    return capture,click,box

def visual_unit_count(image):
    """Match foreground digit masks, independent of sand/lighting beneath them."""
    def gold(color):
        r,g,b=color
        return r>180 and g>130 and b<100
    scores=[]
    for count in (0,5):
        with Image.open(TEMPLATES/f'pvp-count-{count}.png') as source:
            reference=source.convert('RGB')
        expected=[gold(color) for color in reference.getdata()]
        positive=[(i%reference.width,i//reference.width) for i,value in enumerate(expected) if value]
        holes=[]
        if count==0 and positive:
            cx=(min(x for x,y in positive)+max(x for x,y in positive))//2
            cy=(min(y for x,y in positive)+max(y for x,y in positive))//2
            holes=[y*reference.width+x for y in range(cy-1,cy+2) for x in range(cx-1,cx+2)
                   if not expected[y*reference.width+x]]
        best=0
        for y in range(541,549):
            for x in range(7,15):
                actual=[gold(color) for color in image.crop((x,y,x+reference.width,y+reference.height)).convert('RGB').getdata()]
                if holes and sum(actual[i] for i in holes)/len(holes)>.25: continue
                union=sum(a or b for a,b in zip(expected,actual))
                score=sum(a and b for a,b in zip(expected,actual))/max(1,union)
                best=max(best,score)
        scores.append((best,count))
    scores.sort(reverse=True)
    if scores[0][0]>=.65 and scores[0][0]-scores[1][0]>=.12: return scores[0][1]
    return None

def unit_count(image):
    count=visual_unit_count(image)
    # Capacity is not needed to establish an empty board; don't guess 7 vs 8.
    if count is not None: return count,None
    crop=image.crop((0,530,180,580)).convert('RGB')
    path=ROOT/'unit-count.png'
    mask=Image.new('L',crop.size)
    mask.putdata([0 if r>180 and g>130 and b<100 else 255 for r,g,b in crop.getdata()])
    mask.resize((540,150)).save(path)
    text=''.join(w['Text'] for w in app.recognize(path,'zh-Hans-CN',True)).replace(' ','')
    count=re.search(r'([0-8])[/／]([0-8])',text)
    if not count:
        crop.resize((540,150)).save(path)
        text=''.join(w['Text'] for w in app.recognize(path,'zh-Hans-CN',True)).replace(' ','')
        count=re.search(r'([0-8])[/／]([0-8])',text)
    if not count: raise RuntimeError('未识别部署单位数量，未重复放置。')
    return int(count[1]),int(count[2])

def read_unit_count(capture):
    frame,count=retry_observation(capture,visual_unit_count,timeout=2)
    if count is not None: return count,None
    return unit_count(frame)

def wait_deployment_frame(capture):
    frame,state=retry_observation(capture,lambda image:'deployment' if stage(image)=='deployment' else None,timeout=3)
    if state is None: raise RuntimeError('等待部署界面稳定后仍未确认，未添加单位。')
    return frame

def wait_start_button(capture):
    def observe(image):
        try: return start_button(image)
        except RuntimeError: return None
    _,result=retry_observation(capture,observe,timeout=3)
    if result is None: raise RuntimeError('重试后仍未定位绿色开战按钮，未点击。')
    return result

def start_button(image):
    # Long horizontal green runs identify the rectangular button and exclude foliage.
    pixels=image.convert('RGB').load();runs=[]
    for y in range(430,610):
        left=None
        for x in range(1100,image.width):
            r,g,b=pixels[x,y];green=g>75 and g>r*1.5 and g>b*1.5
            if green and left is None: left=x
            if left is not None and (not green or x==image.width-1):
                if x-left>=100: runs.append((left,y,x))
                left=None
    if not runs: raise RuntimeError('未定位 PVP 绿色开战按钮。')
    left=min(x for x,y,r in runs);right=max(r for x,y,r in runs)
    top=min(y for x,y,r in runs);bottom=max(y for x,y,r in runs)
    if not 20<=bottom-top<=90: raise RuntimeError('PVP 开战按钮形状不可靠。')
    return ((left+right)//2,(top+bottom)//2),(left,top,right,bottom)

def deploy_single(capture,click,box):
    image=capture()
    if stage(image)!='deployment': raise RuntimeError('未确认 PVP 布置界面，未放单位。')
    existing=[cell for cell in deployment.aircraft_cells() if deployment.gunner_present(image,cell)]
    if len(existing)==1:
        point,_=start_button(capture());click(point)
        return {'unit':'heavy_gunner','count':1,'cell':list(existing[0]),'clicked_start':True,'start_point':list(point),'resumed':True}
    count,limit=read_unit_count(capture)
    if count!=0: raise RuntimeError('PVP 布置不是空阵，停止追加单位。')
    for attempt in range(16):
        try:
            icon=deployment.find_icon(image);break
        except RuntimeError:
            if attempt==15: raise
            capture();mouse.move(box[0]+500,box[1]+730);mouse.scroll(-240)
            time.sleep(.1);image=capture()
    click(icon)
    deadline=time.monotonic()+3
    while True:
        image=capture()
        players=[cell for cell in deployment.aircraft_cells() if deployment.gunner_present(image,cell)]
        if len(players)==1: break
        if time.monotonic()>=deadline: raise RuntimeError('PVP 未可靠定位单个机枪手，未追加。')
        time.sleep(.08)
    image.save(ROOT/'deployment.png')
    point,region=start_button(image)
    fresh=capture()
    fresh_point,_=start_button(fresh)
    if abs(fresh_point[0]-point[0])+abs(fresh_point[1]-point[1])>15:
        raise RuntimeError('PVP 开战按钮位置改变，未点击。')
    click(fresh_point)
    return {'unit':'heavy_gunner','count':1,'cell':list(players[0]),'clicked_start':True,
            'start_point':list(point)}

def count_marks(image):
    return tuple(r>180 and g>130 and b<100 for r,g,b in
                 image.crop((10,544,27,565)).convert('RGB').getdata())

def place_icon(capture,click,box,template):
    image=capture()
    for attempt in range(16):
        try:
            icon=deployment.find_icon(image,template);break
        except RuntimeError:
            if attempt==15: raise
            capture();mouse.move(box[0]+500,box[1]+730);mouse.scroll(-240)
            time.sleep(.12);image=capture()
    before=count_marks(image);click(icon)
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        image=capture()
        current=stage(image)
        if current is None:
            time.sleep(.1);continue
        if current!='deployment': raise RuntimeError('部署阶段已结束，停止添加单位。')
        if sum(a!=b for a,b in zip(before,count_marks(image)))>8:
            time.sleep(.2);return capture()
        time.sleep(.08)
    raise RuntimeError('点击单位后数量未改变，停止重复放置。')

def deploy_team(capture,click,box):
    gunner=unit_ai('heavy_gunner')
    image=wait_deployment_frame(capture)
    if read_unit_count(capture)[0]!=0: raise RuntimeError('本轮阵容要求空阵开始，停止追加。')
    image=place_icon(capture,click,box,gunner.icon_template)
    def find_players(frame):
        players=[cell for cell in deployment.aircraft_cells() if gunner.present(frame,cell)]
        return players or None
    image,players=retry_observation(capture,find_players,timeout=3)
    if not players: raise RuntimeError('已放下单位，但未定位机枪手。')
    cell=min(players,key=lambda p:abs(p[0]-599)+abs(p[1]-390))
    for number in range(6):
        image=place_icon(capture,click,box,'bigfoot-baby-icon.png')
    image.save(ROOT/'deployment.png')
    point,_=wait_start_button(capture);click(point)
    return {'unit':'heavy_gunner_and_bigfoot_babies','count':7,'babies':6,
            'cell':list(cell),'clicked_start':True,'start_point':list(point)}

@lru_cache(maxsize=1)
def laugh_templates():
    result=[]
    for path in TEMPLATES.glob('pvp-laugh*.png'):
        with Image.open(path) as source:
            result.append(source.convert('RGB').crop((8,8,55,58)).resize((16,16)))
    return result

def locate_laugh(frame):
    best=(999,None)
    for y in range(94,185,4):
        for x in range(150,425,4):
            crop=frame.crop((x,y,x+47,y+50)).convert('RGB').resize((16,16))
            score=min(sum(ImageStat.Stat(ImageChops.difference(crop,template)).mean)/3
                      for template in laugh_templates())
            if score<best[0]: best=(score,(x+23,y+25))
    return best[1] if best[0]<20 else None

def send_laugh(capture,click):
    frame=capture()
    if stage(frame)!='deployment': raise RuntimeError('未进入部署，未发送表情。')
    if not locate_laugh(frame): click((195,130))
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        frame=capture();point=locate_laugh(frame)
        if point:
            click(point);time.sleep(.2)
            capture().save(ROOT/'emote-sent.png')
            return {'sent':True,'name':'laugh'}
        time.sleep(.08)
    frame.save(ROOT/'emote-menu.png')
    return {'sent':False,'name':'laugh','reason':'not_located','continue_deployment':True}

def opening_sweep(capture,click,cell,timeout=90):
    gunner=unit_ai('heavy_gunner');skill=gunner.pvp_opening_skill
    deadline=time.monotonic()+timeout
    last_saved=0;missing_since=None
    while time.monotonic()<deadline:
        frame=capture()
        if time.monotonic()-last_saved>.5:
            frame.save(ROOT/'opening-wait.png');last_saved=time.monotonic()
        if stage(frame) in ('defeat','victory','settlement'): return {'released':False,'battle_ended':True,'outcome':stage(frame)}
        if battle_started(frame):
            if not gunner.present(frame,cell):
                if missing_since is None: missing_since=time.monotonic()
                if time.monotonic()-missing_since>.8:
                    return {'released':False,'gunner_lost':True}
            else: missing_since=None
        if battle_started(frame) and our_turn(frame):
            click(cell);time.sleep(.12)
            selected=capture()
            if not battle_started(selected):
                time.sleep(.15);continue
            if not combat.skill_panel_visible(selected):
                time.sleep(.12);continue
            if gunner.cooldown(selected,skill,read_turns=False)['blocked']:
                raise RuntimeError('PVP 第一次操作时一技能已冷却，未盲点。')
            click(gunner.skill_points[skill]);time.sleep(gunner.aim_settle_seconds)
            preview=capture()
            if not battle_started(preview): continue
            # Skill 1 accepts any covered tile; fixed front-row middle avoids
            # requiring PVE sprite outlines for arbitrary PVP opponents.
            target=list(gunner.pvp_opening_target);click(target)
            preview.save(ROOT/'opening-preview.png')
            deadline_release=time.monotonic()+1.2
            while time.monotonic()<deadline_release:
                after=capture()
                if not combat.skill_panel_visible(after) or gunner.cooldown(after,skill,read_turns=False)['blocked']:
                    return {'released':True,'skill':skill,'target':target}
                time.sleep(.1)
            return {'released':None,'clicked':True,'skill':skill,'target':target,
                    'confirmation':'transition_not_observed','continue_pass':True}
        time.sleep(.12)
    raise RuntimeError('等待 PVP 首次可操作回合超时。')

def pass_available(image):
    colors=image.crop((30,190,108,216)).convert('RGB').getdata()
    return sum(r>190 and 70<g<145 and b<60 and r-g>80 for r,g,b in colors)>600

def battle_started(image):
    # An enabled pass button is definitive, including blue skill previews.
    if pass_available(image): return True
    # Deployment's cyan board remains until both players have pressed Start.
    colors=image.crop((700,250,1200,370)).convert('RGB').getdata()
    cyan=sum(g>150 and b>140 and g>r*1.15 and b>r*1.15 for r,g,b in colors)
    return cyan<1500

def our_turn(image):
    if pass_available(image): return True
    colors=image.crop((250,700,900,749)).convert('RGB').getdata()
    return sum(max(r,g,b)<85 for r,g,b in colors)>1800

def finish_defeat(capture,click):
    attempts=0;last_click=-10;deadline=time.monotonic()+45
    pending_point=None;stable_since=0;returned_since=None
    while time.monotonic()<deadline:
        frame=capture();current=stage(frame)
        if current in ('map','ranked'):
            if returned_since is None: returned_since=time.monotonic()
            if time.monotonic()-returned_since>.35:
                return {'returned':current,'confirm_attempts':attempts}
            time.sleep(.1);continue
        returned_since=None
        if current in ('defeat','victory','settlement') and time.monotonic()-last_click>=1.2:
            if attempts>=5: raise RuntimeError('PVP 结算确定五次后仍未切换，已停止。')
            frame.save(ROOT/'defeat.png')
            point=result_button(frame)
            if point is None: pending_point=None;time.sleep(.1);continue
            if pending_point is None or abs(point[0]-pending_point[0])+abs(point[1]-pending_point[1])>8:
                pending_point=point;stable_since=time.monotonic();time.sleep(.1);continue
            if time.monotonic()-stable_since<.2: time.sleep(.1);continue
            fresh=capture();fresh_outcome,fresh_point=result_dialog(fresh)
            if fresh_outcome is None or fresh_point is None: time.sleep(.1);continue
            if abs(point[0]-fresh_point[0])+abs(point[1]-fresh_point[1])>8:
                pending_point=None;continue
            point=fresh_point
            click(point)
            attempts+=1;last_click=time.monotonic()
        time.sleep(.1)
    frame.save(ROOT/'settlement-unrecognized.png')
    raise RuntimeError('PVP 结算确认后等待返回超时，已保存 settlement-unrecognized.png。')

def lose_battle(capture,click,progress=lambda text:None,timeout=300):
    deadline=time.monotonic()+timeout;passes=0;verified=False
    next_check=time.monotonic()
    while time.monotonic()<deadline:
        while time.monotonic()<next_check:
            control.check();time.sleep(min(.1,max(0,next_check-time.monotonic())))
        frame=capture();current=stage(frame)
        frame.save(ROOT/'after.png')
        if current in ('defeat','victory','settlement'):
            label={'defeat':'战败','victory':'战胜（对手可能退出）','settlement':'对局结束'}[current]
            progress('PVP '+label+'，正在确认…')
            return {'passes':passes,'outcome':current,'settlement':finish_defeat(capture,click)}
        if current in ('map','ranked'):
            _,confirmed=retry_observation(capture,lambda image:stage(image) if stage(image) in ('map','ranked') else None,timeout=1)
            if confirmed:
                return {'passes':passes,'outcome':'unknown','settlement':{'returned':confirmed,'already_returned':True}}
        if battle_started(frame) and our_turn(frame):
            if our_turn(capture()):
                click((70,203));passes+=1
                progress(f'PVP 已点击放弃 {passes} 次，3 秒后检查…')
        next_check=time.monotonic()+3
    raise RuntimeError('PVP 送分战斗超过 5 分钟，已停止。')

def run_round(progress=lambda text:None):
    capture,click,box=game_capture()
    if stage(capture()) in ('defeat','victory','settlement'):
        return {'status':'complete','resumed_defeat':True,'settlement':finish_defeat(capture,click)}
    report={'match':start_match(progress)}
    if report['match']['status']=='deployment':
        guarded_capture,guarded_click=deployment_io(capture,click)
        try:
            progress('部署前发送哈哈笑表情…')
            report['emote']=send_laugh(guarded_capture,guarded_click)
            progress('PVP 已找到对手，放一个重机枪手和六个大脚怪宝宝，然后开战…')
            report['deployment']=deploy_team(guarded_capture,guarded_click,box)
        except DeploymentSettled as ended:
            progress('部署期间对局已结束，停止放单位并确认结算…')
            report.update(deployment_interrupted=True,status='complete')
            report['battle']={'passes':0,'outcome':ended.outcome,
                              'settlement':finish_defeat(capture,click)}
            (ROOT/'round-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            return report
        progress('等待首次可操作回合，释放一次一技能横扫…')
        report['opening']=opening_sweep(capture,click,report['deployment']['cell'])
    report['battle']=lose_battle(capture,click,progress)
    report['status']='complete'
    (ROOT/'round-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def run_batch(rounds=5,progress=lambda text:None):
    report={'requested':rounds,'completed':0,'rounds':[],'status':'running'}
    path=ROOT/'batch-result.json'
    try:
        for number in range(1,rounds+1):
            control.check()
            capture,_,_=game_capture()
            wait_start_stage(capture)
            progress(f'PVP 连续测试 {number}/{rounds} 开始。')
            result=run_round(progress)
            report['rounds'].append(result);report['completed']=number
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            progress(f'PVP 连续测试 {number}/{rounds} 完成并返回基地。')
        report['status']='complete'
    except Exception as exc:
        report.update(status='stopped',error=str(exc));raise
    finally:
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def run_loop(progress=lambda text:None):
    report={'completed':0,'victories':0,'defeats':0,'recent_rounds':[],'status':'running'}
    path=ROOT/'loop-result.json'
    try:
        while True:
            control.check()
            capture,click,_=game_capture()
            _,current=wait_start_stage(capture,allow_started=True)
            if current in ('victory','defeat','settlement'):
                progress('检测到尚未确认的 PVP 结算，先确认返回基地…')
                finish_defeat(capture,click)
                continue
            number=report['completed']+1
            progress(f'全自动 PVP：第 {number} 轮开始。按 Esc 停止。')
            result=run_round(progress)
            report['completed']=number
            outcome=result.get('battle',{}).get('outcome')
            if outcome=='victory': report['victories']+=1
            if outcome=='defeat': report['defeats']+=1
            report['recent_rounds']=(report['recent_rounds']+[result])[-5:]
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            progress(f'已完成 {number} 轮 PVP，结算返回基地，开始下一轮。')
    except Exception as exc:
        report.update(status='stopped',reason=str(exc));raise
    finally:
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--loop',action='store_true')
    mode.add_argument('--rounds',type=int)
    options=parser.parse_args()
    control.reset()
    progress=lambda text:print(text,flush=True)
    result=run_loop(progress) if options.loop else run_batch(options.rounds,progress) if options.rounds else run_round(progress)
    print(json.dumps(result,ensure_ascii=True))
