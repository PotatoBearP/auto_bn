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
    hwnd = app.find_game()
    app.focus_game(hwnd)
    box = app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('当前布阵校准适用于 1366×768 游戏画面，请恢复该尺寸。')
    reports=[]
    def check():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，已停止布阵。')
    def wait_gunner(position):
        deadline=time.monotonic()+2
        while True:
            check()
            frame=ImageGrab.grab(bbox=box,all_screens=True)
            if gunner_present(frame,position) or time.monotonic()>=deadline:
                return frame
            time.sleep(.08)
    for column in columns:
        check()
        image=ImageGrab.grab(bbox=box,all_screens=True)
        image.save(ROOT/f'deployment-before-{column}.png')
        destination=PROFILE['front_row'][column-1]
        if gunner_present(image,destination):
            reports.append({'column':column,'status':'already_placed'})
            continue
        green=sum(g>100 and g>r*1.4 and g>b*1.4 for r,g,b in image.convert('RGB').crop((1200,450,1360,570)).getdata())
        if green<1500: raise RuntimeError('未检测到布阵界面的绿色开战按钮。')
        if gunner_present(image,PROFILE['spawn']): raise RuntimeError('默认格已有重机枪手，请先调整已有单位。')
        icon=find_icon(image)
        mouse.click(box[0]+icon[0],box[1]+icon[1])
        image=wait_gunner(PROFILE['spawn'])
        if not gunner_present(image,PROFILE['spawn']): raise RuntimeError('点选后未检测到默认格中的重机枪手。')
        actual=mouse.drag((box[0]+599,box[1]+390),(box[0]+destination[0],box[1]+destination[1]),check)
        image=wait_gunner(destination)
        image.save(ROOT/f'deployment-after-{column}.png')
        if not gunner_present(image,destination): raise RuntimeError(f'第 {column} 格未通过摆放检查。')
        reports.append({'column':column,'status':'placed','actual_cursor':list(actual)})
    check()
    image=ImageGrab.grab(bbox=box,all_screens=True)
    destination=PROFILE['experience_aircraft']
    if aircraft_present(image,destination):
        reports.append({'unit':'first_aircraft','cell':destination,'status':'already_placed'})
    else:
        existing=[cell for cell in aircraft_cells() if aircraft_present(image,cell)]
        if len(existing)>1: raise RuntimeError('检测到多个飞机位置，停止重复部署。')
        if not existing:
            icon=None
            # Toolbar wheel scrolling only; never pan the board while searching.
            for attempt in range(12):
                check()
                try:
                    icon=find_icon(image,'first-aircraft-icon.png')
                    break
                except RuntimeError:
                    if attempt==11: raise
                    mouse.move(box[0]+500,box[1]+730)
                    mouse.scroll(240)
                    time.sleep(.12)
                    image=ImageGrab.grab(bbox=box,all_screens=True)
            mouse.click(box[0]+icon[0],box[1]+icon[1])
            deadline=time.monotonic()+3
            while True:
                check()
                image=ImageGrab.grab(bbox=box,all_screens=True)
                existing=[cell for cell in aircraft_cells() if aircraft_present(image,cell)]
                if existing: break
                if time.monotonic()>=deadline: raise RuntimeError('点击后未定位第一架飞机，停止重复点击。')
                time.sleep(.08)
        if len(existing)!=1: raise RuntimeError('飞机生成格不唯一，未拖动。')
        source=existing[0]
        if source!=tuple(destination):
            mouse.drag((box[0]+source[0],box[1]+source[1]),
                       (box[0]+destination[0],box[1]+destination[1]),check)
        deadline=time.monotonic()+2
        while True:
            check()
            image=ImageGrab.grab(bbox=box,all_screens=True)
            if aircraft_present(image,destination): break
            if time.monotonic()>=deadline: raise RuntimeError('飞机后排第 2 格摆放检查失败，未开战。')
            time.sleep(.08)
        reports.append({'unit':'first_aircraft','cell':destination,'status':'placed'})
    ImageGrab.grab(bbox=box,all_screens=True).save(ROOT/'deployment-complete.png')
    (ROOT/'deployment-result.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    return reports

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

def start_battle():
    hwnd=app.find_game(); app.focus_game(hwnd)
    box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('当前开战前摆放检查适用于 1366×768 游戏画面。')
    image=ImageGrab.grab(bbox=box,all_screens=True)
    if not all(gunner_present(image,PROFILE['front_row'][i-1]) for i in (2,4)):
        raise RuntimeError('第一排 2、4 格未通过机枪手摆放检查，未开战。')
    if not aircraft_present(image,PROFILE['experience_aircraft']):
        raise RuntimeError('第一个机枪手后方未通过飞机摆放检查，未开战。')
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
    return result

def deploy_and_start():
    placements=deploy()
    return {'placements':placements,'start':start_battle()}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--columns',nargs='+',type=int,default=[2,4],choices=range(1,6))
    parser.add_argument('--start-only',action='store_true')
    parser.add_argument('--no-start',action='store_true')
    args=parser.parse_args()
    if args.start_only: result=start_battle()
    elif args.no_start: result=deploy(args.columns)
    else: result={'placements':deploy(args.columns),'start':start_battle()}
    print(json.dumps(result,ensure_ascii=True))
