"""Verified gunner deployment for the calibrated 1366x768 board."""
import argparse
import json
import time
from functools import lru_cache
from PIL import Image, ImageGrab, ImageChops, ImageStat
import app
import mouse_backend as mouse
import control

from paths import DEPLOYMENT, TEMPLATES
ROOT = DEPLOYMENT
PROFILE = {'size':[1366,768], 'front_row':[[378,280],[489,335],[599,390],[709,445],[819,500]],
           'spawn':[599,390], 'experience_aircraft':[379,390]}

@lru_cache(maxsize=1)
def aircraft_features():
    with Image.open(TEMPLATES/'first-aircraft-body.png') as source:
        reference=source.convert('RGB')
    green=[];dark=[]
    for y in range(0,reference.height,2):
        for x in range(0,reference.width,2):
            r,g,b=reference.getpixel((x,y))
            if g>60 and g>r*1.15 and g>b*1.2: green.append((x,y))
            if max(r,g,b)<65: dark.append((x,y))
    return green,dark

def aircraft_present(image,cell):
    # Tail and missile racks are stable; ignore rotor and selection overlays.
    green,dark=aircraft_features()
    x,y=cell
    pixels=image.convert('RGB').load()
    for dy in range(-12,13,4):
        for dx in (-4,0,4):
            colors=[pixels[x-25+dx+ox,y-45+dy+oy] for ox,oy in green]
            matches=sum(g>60 and g>r*1.15 and g>b*1.2 for r,g,b in colors)
            blacks=sum(max(pixels[x-25+dx+ox,y-45+dy+oy])<85 for ox,oy in dark)
            if matches/max(1,len(green))>.65 and blacks/max(1,len(dark))>.65:
                return True
    return False

def aircraft_cells():
    return [(x-110*row,y+55*row) for row in (0,1,2)
            for column,(x,y) in enumerate(PROFILE['front_row'],1)
            if row<2 or column in (2,3,4)]

def gunner_present(image,cell):
    x,y=cell
    pixels=list(image.convert('RGB').crop((x-40,y-120,x+50,y-10)).getdata())
    orange=sum(r>180 and 70<g<185 and b<130 and r>g*1.25 for r,g,b in pixels)
    dark=sum(max(r,g,b)<85 for r,g,b in pixels)
    return orange>800 and dark>500

def find_icon(image,template='heavy-gunner-icon.png'):
    reference=Image.open(TEMPLATES/template).convert('RGB').resize((16,14))
    best=(999,None)
    for x in range(0,image.width-47,2):
        sample=image.crop((x,713,x+47,751)).convert('RGB').resize((16,14))
        score=sum(ImageStat.Stat(ImageChops.difference(reference,sample)).mean)/3
        if score<best[0]: best=(score,(x+23,730))
    if best[0]>20: raise RuntimeError('未可靠匹配单位图标，请滚动单位栏使其图标可见：'+template)
    return best[1]

def deploy(columns=(2,4)):
    import formation
    config=formation.validate({'version':1,'units':[
        {'row':1,'column':column,'unit':'heavy_gunner'} for column in columns]})
    return deploy_formation(config)

def locate_start_button(image):
    pixels=image.convert('RGB').load()
    runs=[]
    for y in range(400,min(620,image.height)):
        start=None
        for x in range(1100,image.width):
            r,g,b=pixels[x,y]
            green=g>75 and g>r*1.5 and g>b*1.5
            if green and start is None: start=x
            if start is not None and (not green or x==image.width-1):
                if x-start>=100: runs.append((start,y,x))
                start=None
    if not runs: raise RuntimeError('未找到绿色开战按钮，已停止。')
    # Keep separate green controls separate: a selected unit's HP bar below
    # the start button must not pull the click into the space between them.
    groups=[]
    for run in runs:
        if not groups or run[1]-groups[-1][-1][1]>28: groups.append([])
        groups[-1].append(run)
    groups=[group for group in groups if 18<=group[-1][1]-group[0][1]<=90]
    if not groups: raise RuntimeError('绿色区域不符合开战按钮尺寸，已停止。')
    runs=max(groups,key=lambda group:sum(right-left for left,y,right in group))
    left=min(r[0] for r in runs); right=max(r[2] for r in runs)
    top=min(r[1] for r in runs); bottom=max(r[1] for r in runs)
    crop=image.crop((left,max(0,top-5),right,min(image.height,bottom+6)))
    path=ROOT/'start-button.png'
    crop.resize((crop.width*3,crop.height*3)).save(path)
    text=''.join(w['Text'] for w in app.recognize(path,'zh-Hans-CN',True))
    if '开战' not in text:
        crop.convert('L').point(lambda v:0 if v>210 else 255).resize((crop.width*3,crop.height*3)).save(path)
        text=''.join(w['Text'] for w in app.recognize(path,'zh-Hans-CN',True))
    if '开战' not in text: raise RuntimeError('绿色按钮未通过“开战”文字核对，已停止。')
    return ((left+right)//2,(top+bottom)//2),(left,top,right,bottom),text


def start_button_visible(image):
    """Cheap observation only; locate_start_button still validates before input."""
    colors=image.convert('RGB').crop((1190,460,1360,525)).getdata()
    return sum(g>75 and g>r*1.5 and g>b*1.5 for r,g,b in colors)>1200

def deploy_formation(config):
    """Place registered units in configured cells; discover their actual spawn cell."""
    import formation
    config=formation.validate(config)
    hwnd=app.find_game();app.focus_game(hwnd);box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('自定义部署适用于约 1366×768 游戏画面。')
    def check():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，停止部署。')
    def capture():
        check();return ImageGrab.grab(bbox=box,all_screens=True)
    board=[formation.position(r,c) for r,c in formation.cells()]
    reports=[]
    def place(destination,present,template,label):
        image=capture()
        if present(image,destination): return 'already_placed'
        # Keep the central spawn free until the last placement.
        before={cell for cell in board if present(image,cell)}
        for attempt in range(37):
            try:
                icon=find_icon(image,template);break
            except RuntimeError:
                if attempt==36: raise
                check();mouse.move(box[0]+500,box[1]+730)
                mouse.scroll(-240 if attempt<12 else 240)
                time.sleep(.12);image=capture()
        locate_start_button(image) # Still in deployment, before adding a unit.
        check();mouse.click(box[0]+icon[0],box[1]+icon[1])
        deadline=time.monotonic()+3
        while True:
            image=capture()
            spawned=[cell for cell in board if cell not in before and present(image,cell)]
            if len(spawned)==1: break
            if time.monotonic()>=deadline:
                raise RuntimeError(f'{label}生成格未可靠定位，停止重复添加。')
            time.sleep(.08)
        source=spawned[0]
        if source!=destination:
            if any(ai.present(image,destination) for _,ai in formation.units(config)):
                raise RuntimeError('目标格已有单位，停止拖动。')
            mouse.drag((box[0]+source[0],box[1]+source[1]),
                       (box[0]+destination[0],box[1]+destination[1]),check)
        deadline=time.monotonic()+3
        while not present(capture(),destination):
            if time.monotonic()>=deadline: raise RuntimeError(f'{label}目标格检查失败，未开战。')
            time.sleep(.08)
        return 'placed'
    entries=sorted(config['units'],key=lambda u:formation.position(u['row'],u['column'])==tuple(PROFILE['spawn']))
    from unit_ai import get
    for entry in entries:
        ai=get(entry['unit']);cell=formation.position(entry['row'],entry['column'])
        status=place(cell,ai.present,ai.icon_template,ai.name)
        reports.append({**entry,'name':ai.name,'cell':list(cell),'status':status})
    capture().save(ROOT/'deployment-complete.png')
    (ROOT/'deployment-result.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    return reports

def start_battle(config=None,verify_placement=True):
    hwnd=app.find_game(); app.focus_game(hwnd)
    box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('当前开战前摆放检查适用于 1366×768 游戏画面。')
    image=ImageGrab.grab(bbox=box,all_screens=True)
    import formation
    config=formation.validate(config or formation.defaults())
    if verify_placement:
        for cell,ai in formation.units(config):
            if not ai.present(image,cell): raise RuntimeError(f'{ai.name}在配置格 {cell} 未通过摆放检查，未开战。')
    point,region,text=locate_start_button(image)
    image.save(ROOT/'start-before.png')
    if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
        raise RuntimeError('窗口或焦点改变，未开战。')
    fresh=ImageGrab.grab(bbox=box,all_screens=True)
    difference=ImageStat.Stat(ImageChops.difference(image.crop(region),fresh.crop(region)))
    if sum(difference.mean)/3>12: raise RuntimeError('开战按钮画面改变，已停止。')
    mouse.click(box[0]+point[0],box[1]+point[1])
    # Wait through the server loading overlay; never retry the click while loading.
    started=time.monotonic()
    while True:
        control.check()
        time.sleep(.15)
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('已点击开战，但窗口变化，无法继续确认结果。')
        after=ImageGrab.grab(bbox=box,all_screens=True)
        after.save(ROOT/'start-after.png')
        green=sum(g>75 and g>r*1.5 and g>b*1.5 for r,g,b in after.convert('RGB').crop(region).getdata())
        if green<300 or time.monotonic()-started>=20: break
    result={'clicked':True,'client':list(point),'screen':[box[0]+point[0],box[1]+point[1]],
            'button_text':text,'start_button_disappeared':green<300}
    (ROOT/'start-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if not result['start_button_disappeared']:
        raise RuntimeError('已点击一次开战，等待 20 秒后按钮仍可见；可能仍在加载，请查看游戏。')
    from combat import reset_battle_state
    reset_battle_state()
    formation.activate(config)
    return result

def deploy_and_start():
    import formation
    config=formation.load()
    placements=deploy_formation(config)
    return {'formation':config,'placements':placements,'start':start_battle(config)}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--columns',nargs='+',type=int,choices=range(1,6))
    parser.add_argument('--start-only',action='store_true')
    parser.add_argument('--no-start',action='store_true')
    args=parser.parse_args()
    import formation
    config=formation.load()
    if args.columns is not None:
        config=formation.validate({'version':1,'units':[{'row':1,'column':c,'unit':'heavy_gunner'}
                                  for c in args.columns]})
    if args.start_only: result=start_battle(config)
    elif args.no_start: result=deploy_formation(config)
    else: result={'formation':config,'placements':deploy_formation(config),'start':start_battle(config)}
    print(json.dumps(result,ensure_ascii=True))
