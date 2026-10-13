"""Battle Nations desktop automation. Python 3.10+, Pillow, Windows OCR."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk
from PIL import ImageGrab, ImageChops, ImageStat, ImageDraw, ImageOps
from paths import ENCOUNTER, OCR, TEMPLATES
from functools import lru_cache
import control

ROOT = Path(__file__).resolve().parent
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SetProcessDPIAware()
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

class MouseInput(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

class InputPayload(ctypes.Union):
    _fields_ = [('mi', MouseInput)]

class Input(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('payload', InputPayload)]

user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

def cursor_position():
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return point.x, point.y

def close_existing_gui():
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    def visit(hwnd, _):
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == 'Battle Nations · 遭遇战助手':
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True
    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    time.sleep(0.2)

def send_mouse(flags):
    event = Input(type=0, payload=InputPayload(mi=MouseInput(dwFlags=flags)))
    if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
        raise RuntimeError('Windows 未接受鼠标输入，请让工具与游戏使用相同权限运行。')

def move_cursor_input(x, y):
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    mi = MouseInput(dx=round((x-left)*65535/(width-1)),
                    dy=round((y-top)*65535/(height-1)), dwFlags=0x8001|0x4000)
    event = Input(type=0,payload=InputPayload(mi=mi))
    if user32.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input)) != 1:
        raise RuntimeError('Windows 未接受鼠标移动事件。')

def move_and_click(hwnd, box, x, y):
    """Allow the game to process mouse movement before pressing the button."""
    start_x, start_y = cursor_position()
    for step in range(1, 21):
        control.check()
        if user32.GetForegroundWindow() != hwnd or bounds(hwnd) != box:
            raise RuntimeError('移动期间窗口或焦点改变，已取消点击。')
        px = round(start_x + (x-start_x)*step/20)
        py = round(start_y + (y-start_y)*step/20)
        if not user32.SetCursorPos(px, py):
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.02)
    time.sleep(0.4)
    actual = cursor_position()
    if abs(actual[0]-x) > 2 or abs(actual[1]-y) > 2:
        raise RuntimeError(f'鼠标没有到达目标：目标 {(x,y)}，实际 {actual}。')
    if user32.GetForegroundWindow() != hwnd or bounds(hwnd) != box:
        raise RuntimeError('点击前焦点或位置改变，已取消点击。')
    ImageGrab.grab(bbox=box, all_screens=True).save(ENCOUNTER / 'game-hover.png')
    control.check()
    send_mouse(0x0002)
    try:
        time.sleep(0.15)
    finally:
        send_mouse(0x0004)
    return {'requested': [x,y], 'actual_before_click': list(actual), 'input_method': 'SendInput'}

def drag_unit(hwnd, box, source, destination):
    def check():
        if user32.GetForegroundWindow() != hwnd or bounds(hwnd) != box:
            raise RuntimeError('拖放期间窗口或焦点改变，已停止。')
    check()
    sx, sy = box[0]+source[0], box[1]+source[1]
    dx, dy = box[0]+destination[0], box[1]+destination[1]
    import mouse_backend as mouse
    move_cursor_input(sx,sy)
    time.sleep(0.4)
    check()
    if cursor_position() != (sx,sy):
        raise RuntimeError('鼠标未到达单位图标。')
    mouse.drag((sx,sy),(dx,dy),check)
    time.sleep(1)
    return {'source':list(source), 'destination':list(destination), 'actual':list(cursor_position())}

def find_game():
    matches = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        text = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, text, len(text))
        if text.value.strip().lower() == 'battle nations' and user32.IsWindowVisible(hwnd):
            matches.append(hwnd)
        return True
    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    if len(matches) != 1:
        raise RuntimeError('需要一个已打开的 Battle Nations 游戏窗口。')
    return matches[0]

def bounds(hwnd):
    rect, point = wintypes.RECT(), wintypes.POINT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise RuntimeError('读取游戏窗口位置失败。')
    return (point.x, point.y, point.x + rect.right, point.y + rect.bottom)

def recognize(path, language='en-US', all_words=False):
    control.check()
    result = subprocess.run([
        'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA',
        '-File', str(ROOT / 'battle-tool.ps1'), '-ImagePath', str(path),
        '-Language', language, *(['-AllWords'] if all_words else [])
    ], capture_output=True, encoding='utf-8', errors='replace', timeout=40,
       creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Windows OCR 失败：' + result.stderr[-1200:])
    data = json.loads(result.stdout.strip() or '[]')
    return [data] if isinstance(data, dict) else (data or [])

def iter_attack_buttons(image):
    """Find ochre button interiors, then OCR each enlarged button."""
    width, height = image.size
    mask = bytearray(1 if (r > 90 and g > 45 and b < 90 and r > g*1.2 and g > b*1.3)
                     or (r>90 and g<65 and b<65 and r>g*2 and r>b*2) else 0
                     for r, g, b in image.convert('RGB').getdata())
    rectangles = []
    for start in range(len(mask)):
        if not mask[start]:
            continue
        mask[start] = 0
        stack = [start]
        left = right = start % width
        top = bottom = start // width
        count = 0
        while stack:
            index = stack.pop()
            x, y = index % width, index // width
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            count += 1
            for neighbor in (index-width if y else -1, index+width if y+1 < height else -1,
                             index-1 if x else -1, index+1 if x+1 < width else -1):
                if neighbor >= 0 and mask[neighbor]:
                    mask[neighbor] = 0
                    stack.append(neighbor)
        w, h = right-left+1, bottom-top+1
        if 65 <= w <= 230 and 7 <= h <= 35 and w/h >= 3 and count/(w*h) > 0.45:
            rectangles.append((left, top, right+1, bottom+1))
    # OCR lazily in map reading order; stop consuming after the first infected.
    for rect in sorted(rectangles,key=lambda r:((r[1]+r[3])//2,(r[0]+r[2])//2)):
        control.check()
        crop = image.crop((max(0, rect[0]-3), max(0, rect[1]-3), min(width, rect[2]+3), min(height, rect[3]+3)))
        path = OCR / 'input-button.png'
        crop.resize((crop.width*4, crop.height*4)).save(path)
        text = ''.join(item['Text'] for item in recognize(path, all_words=True)).lower()
        if 'attack' not in text:
            # At minimum zoom, isolate the white lettering from ochre/red fill.
            letters=crop.convert('L').point(lambda value:0 if value>210 else 255)
            letters=ImageOps.expand(letters,border=4,fill=255)
            letters.resize((letters.width*6,letters.height*6)).save(path)
            text=''.join(item['Text'] for item in recognize(path,all_words=True)).lower()
        if 'attack' in text:
            yield {'Text': 'Attack!', 'X': (rect[0]+rect[2])//2, 'Y': (rect[1]+rect[3])//2}

def locate_attack_buttons(image):
    return list(iter_attack_buttons(image))

@lru_cache(maxsize=1)
def mammoth_avatar():
    from PIL import Image
    with Image.open(TEMPLATES/'mammoth-avatar.png') as reference:
        return reference.convert('RGB')

def mammoth_card(image,attack):
    x,y=attack['X'],attack['Y']
    reference=mammoth_avatar()
    for dx in (-6,0,6):
        for dy in (-4,0,4):
            sample=image.crop((x-122+dx,y-41+dy,x-90+dx,y-9+dy)).convert('RGB')
            if sum(ImageStat.Stat(ImageChops.difference(sample,reference)).mean)/3<20:
                return True,'猛犸头像'
    if y<80: return False,''
    crop=image.crop((max(0,x-70),y-82,min(image.width,x+70),y-32)).resize((700,250))
    path=OCR/'input-card-exclusion.png'
    crop.save(path)
    text=''.join(w['Text'] for w in recognize(path,'zh-Hans-CN',True))
    if not text.strip():
        cleaned=crop.convert('L').point(lambda v:0 if v>200 else 255)
        ImageOps.expand(cleaned,border=20,fill=255).save(path)
        text=''.join(w['Text'] for w in recognize(path,'zh-Hans-CN',True))
    return '猛犸' in text or 'mammoth' in text.lower(),text

def infected_candidates(image, attacks,first_only=False):
    """Check the title above Attack; avatar artwork may vary."""
    accepted, details = [], []
    for index, attack in enumerate(attacks):
        x, y = attack['X'], attack['Y']
        if y<80: continue # A clipped card has no complete title to verify.
        region = (max(0, x-60), max(0, y-82), min(image.width, x+60), max(1, y-32))
        path = OCR / 'input-card.png'
        crop = image.crop(region)
        crop = crop.resize((crop.width*5, crop.height*5))
        crop.save(path)
        words = recognize(path, 'zh-Hans-CN', True)
        text = ''.join(word['Text'] for word in words)
        if '感染者' not in text and not any(name in text for name in ('猛犸', '海盗')):
            for threshold in (200, 180, 210):
                clean_path = OCR / 'input-card-clean.png'
                cleaned_image = crop.convert('L').point(lambda value: 0 if value > threshold else 255)
                ImageOps.expand(cleaned_image, border=20, fill=255).save(clean_path)
                cleaned = ''.join(word['Text'] for word in recognize(clean_path, 'zh-Hans-CN', True))
                if '感染者' in cleaned:
                    text = cleaned
                    break
        matched = '感染者' in text
        details.append({'attack': attack, 'text': text, 'infected': matched})
        if matched:
            accepted.append({**attack, 'enemy': '感染者', 'card_text': text})
            if first_only: break
    (ENCOUNTER / 'detections.json').write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding='utf-8')
    preview = image.copy()
    draw = ImageDraw.Draw(preview)
    for detail in details:
        x, y = detail['attack']['X'], detail['attack']['Y']
        draw.rectangle((x-65, y-13, x+65, y+13), outline='#44ff88' if detail['infected'] else '#ff5555', width=3)
    preview.save(ENCOUNTER / 'detections.png')
    return accepted

def focus_game(hwnd):
    """Do not delay every action when the game already owns focus."""
    if user32.GetForegroundWindow()!=hwnd:
        user32.SetForegroundWindow(hwnd)
        deadline=time.monotonic()+1.5
        while user32.GetForegroundWindow()!=hwnd:
            control.check()
            if time.monotonic()>=deadline:
                raise RuntimeError('游戏未获得焦点，请切到游戏后重试。')
            time.sleep(.05)
        time.sleep(.12)

def encounter(click=False,allow_empty=False,target=None,first_only=False,entry_only=False):
    control.check()
    hwnd = find_game()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    focus_game(hwnd)
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError('游戏未获得焦点，请切到游戏后重试。')
    box = bounds(hwnd)
    image = ImageGrab.grab(bbox=box, all_screens=True)
    before = ENCOUNTER / 'game-before.png'
    image.save(before)
    attacks=[]
    if target is None:
        def attacks_in_order():
            for attack in iter_attack_buttons(image):
                attacks.append(attack)
                yield attack
        if entry_only:
            candidates=[];details=[]
            for attack in attacks_in_order():
                excluded,text=mammoth_card(image,attack)
                details.append({'attack':attack,'text':text,'infected':'感染者' in text,
                                'entry_only':True,'excluded_mammoth':excluded})
                if excluded: continue
                candidates.append({**attack,'enemy':text or '未核对名称','selection':'visible_attack_entry'})
                break
            (ENCOUNTER/'detections.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            candidates=infected_candidates(image,attacks_in_order(),first_only=first_only or click)
    else:
        candidates=[target]
    if not candidates:
        if allow_empty:
            details=json.loads((ENCOUNTER/'detections.json').read_text(encoding='utf-8'))
            uncertain=[d for d in details if not d['text'].strip()]
            clipped=any(attack['Y']<80 for attack in attacks)
            return {'candidates':0,'clicked':False,'uncertain_cards':len(uncertain),
                    'clipped_cards':clipped,'clear':entry_only or (not uncertain and not clipped)}
        raise RuntimeError('未识别到感染者卡片中的 Attack，请查看 detections.png 和 detections.json。')
    target = candidates[0]
    x, y = box[0] + target['X'], box[1] + target['Y']
    mouse = None
    response_changed = False
    if click:
        if user32.GetForegroundWindow() != hwnd or bounds(hwnd) != box:
            raise RuntimeError('识别期间窗口或焦点发生变化，已取消点击。')
        fresh = ImageGrab.grab(bbox=box, all_screens=True)
        region = (max(0, target['X']-60), max(0, target['Y']-14),
                  min(image.width, target['X']+60), min(image.height, target['Y']+14))
        difference = ImageStat.Stat(ImageChops.difference(image.crop(region), fresh.crop(region)))
        if sum(difference.mean) / len(difference.mean) > 12:
            raise RuntimeError('Attack 区域发生变化，已取消点击，请重试。')
        mouse = move_and_click(hwnd, box, x, y)
        time.sleep(.15)
        after = ImageGrab.grab(bbox=bounds(hwnd), all_screens=True)
        after.save(ENCOUNTER / 'game-after.png')
        if after.size == image.size:
            difference = ImageStat.Stat(ImageChops.difference(image.crop(region), after.crop(region)))
            response_changed = sum(difference.mean) / len(difference.mean) > 20
    report = {'candidates': len(candidates), 'target': target, 'screen': [x, y],
              'clicked': click, 'mouse': mouse, 'target_area_changed': response_changed}
    (ENCOUNTER / 'last-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Battle Nations · 遭遇战助手')
        self.root.geometry('660x870')
        self.root.configure(bg='#161d28')
        self.messages = queue.Queue()
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Action.TButton', font=('Microsoft YaHei UI', 11), padding=12)
        tk.Label(self.root, text='遭遇战助手', font=('Microsoft YaHei UI', 23, 'bold'),
                 fg='#edf4ff', bg='#161d28').pack(anchor='w', padx=26, pady=(25, 10))
        tk.Label(self.root, text='识别感染者卡片中的 Attack，进入感染者遭遇战。',
                 font=('Microsoft YaHei UI', 11), fg='#aebdd0', bg='#161d28').pack(anchor='w', padx=26)
        actions = tk.Frame(self.root, bg='#161d28')
        actions.pack(fill='x', padx=26, pady=25)
        self.scan = ttk.Button(actions, text='只识别', style='Action.TButton', command=lambda: self.run(False))
        self.scan.pack(side='left', fill='x', expand=True, padx=(0, 12))
        self.enter = ttk.Button(actions, text='识别并进入遭遇战', style='Action.TButton', command=lambda: self.run(True))
        self.enter.pack(side='left', fill='x', expand=True)
        self.deploy_button = ttk.Button(self.root, text='布阵并开战：两名机枪手 + 后排飞机',
                                       style='Action.TButton', command=self.run_deployment)
        self.deploy_button.pack(fill='x', padx=26, pady=(0,16))
        self.combat_button = ttk.Button(self.root,text='分析并攻击一次（一、二技能）',
                                        style='Action.TButton',command=self.run_combat)
        self.combat_button.pack(fill='x',padx=26,pady=(0,16))
        self.settlement_button = ttk.Button(self.root,text='确认战利品和经验，返回大地图',
                                             style='Action.TButton',command=self.run_settlement)
        self.settlement_button.pack(fill='x',padx=26,pady=(0,16))
        self.scope_var=tk.StringVar(value='当前可见地图（不拖动）')
        self.scope_box=ttk.Combobox(self.root,textvariable=self.scope_var,
                                    values=('当前可见地图（不拖动）',),state='readonly')
        self.scope_box.pack(fill='x',padx=26,pady=(0,10))
        self.auto_button=ttk.Button(self.root,text='全自动清理：看到 Attack 入口就开打',
                                   style='Action.TButton',command=self.run_automatic)
        self.auto_button.pack(fill='x',padx=26,pady=(0,10))
        self.pvp_button=ttk.Button(self.root,text='全自动 PVP 送分循环（哈哈笑 + 7 单位）',
                                   style='Action.TButton',command=self.run_pvp)
        self.pvp_button.pack(fill='x',padx=26,pady=(0,10))
        self.stop_button=ttk.Button(self.root,text='停止自动化（游戏中也可按 Esc）',
                                   command=self.stop_automatic,state='disabled')
        self.stop_button.pack(fill='x',padx=26,pady=(0,12))
        self.status = tk.Text(self.root, height=8, bg='#0e141e', fg='#c5d9ed', relief='flat',
                              font=('Microsoft YaHei UI', 10), padx=14, pady=12, wrap='word')
        self.status.pack(fill='both', expand=True, padx=26, pady=(0, 24))
        self.set_status('就绪。请让感染者卡片可见。\n核对“感染者”和 Attack，多个匹配时选择最靠上方的一个。')
        self.root.after(100, self.poll)

    def set_status(self, text):
        self.status.configure(state='normal')
        self.status.delete('1.0', 'end')
        self.status.insert('end', text)
        self.status.configure(state='disabled')

    def run(self, click):
        control.reset()
        self.pvp_button.configure(state='disabled')
        self.auto_button.configure(state='disabled')
        self.settlement_button.configure(state='disabled')
        self.combat_button.configure(state='disabled')
        self.deploy_button.configure(state='disabled')
        self.scan.configure(state='disabled'); self.enter.configure(state='disabled')
        self.set_status('正在切换到游戏并识别…')
        self.root.withdraw()
        def worker():
            try:
                report = encounter(click)
                action = ('鼠标已到达目标并点击，目标区域已变化，请查看游戏。' if report['target_area_changed']
                          else '已发送点击，但未检测到目标区域明显变化，请查看游戏。') if click else '识别完成，未点击。'
                self.messages.put(f"{action}\n识别到 {report['candidates']} 个按钮。\n屏幕坐标：{report['screen']}\n识别截图与结果已保存到项目目录。")
            except Exception as exc:
                self.messages.put('操作停止：' + str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def run_deployment(self):
        control.reset()
        self.pvp_button.configure(state='disabled')
        self.auto_button.configure(state='disabled')
        self.settlement_button.configure(state='disabled')
        self.combat_button.configure(state='disabled')
        self.scan.configure(state='disabled'); self.enter.configure(state='disabled')
        self.deploy_button.configure(state='disabled')
        self.set_status('正在核对布阵，完成后点击开战…')
        self.root.withdraw()
        def worker():
            try:
                from deployment import deploy_and_start
                report=deploy_and_start()
                result=report['placements']
                self.messages.put('布阵检查完成，已点击开战，开战按钮已消失。\n'+
                                  '\n'.join((f"机枪手第 {r['column']} 格：" if 'column' in r else '飞机后排第 2 格：')+
                                            ('已在目标格' if r['status']=='already_placed' else '摆放完成') for r in result))
            except Exception as exc:
                self.messages.put('布阵停止：'+str(exc))
        threading.Thread(target=worker,daemon=True).start()

    def run_combat(self):
        control.reset()
        for button in self.action_buttons():
            button.configure(state='disabled')
        self.set_status('读取血条和冷却，预览技能覆盖…')
        self.root.withdraw()
        def worker():
            try:
                from combat import combat_step
                report=combat_step()
                if report.get('battle_ended') and not report.get('released'):
                    self.messages.put('战斗已结束，可以确认结算返回地图。')
                    return
                choice=report['chosen']
                action='已确认技能进入冷却。' if report.get('release_confirmed') else '已发送释放点击，请查看游戏结果。'
                self.messages.put(f"第 {choice['skill']} 技能：{action}\n范围匹配 {choice['hit_count']} 个目标（含溅射估计）。\n"+
                                  ('已等待战斗动画稳定。' if report.get('settled') else '动画尚未确认稳定，请查看游戏。'))
            except Exception as exc:
                self.messages.put('战斗操作停止：'+str(exc))
        threading.Thread(target=worker,daemon=True).start()

    def run_settlement(self):
        control.reset()
        for button in self.action_buttons():
            button.configure(state='disabled')
        self.set_status('识别结算对话框，依次确认并等待大地图…')
        self.root.withdraw()
        def worker():
            try:
                from settlement import finish_battle
                report=finish_battle()
                self.messages.put('结算完成，已返回大地图。\n本次点击确定次数：'+str(len(report['confirmed'])))
            except Exception as exc:
                self.messages.put('结算操作停止：'+str(exc))
        threading.Thread(target=worker,daemon=True).start()

    def action_buttons(self):
        return (self.scan,self.enter,self.deploy_button,self.combat_button,self.settlement_button,self.auto_button,self.pvp_button)

    def run_pvp(self):
        control.reset()
        for button in self.action_buttons(): button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.set_status('全自动 PVP 循环启动：匹配每 4 秒检查，放弃每 3 秒检查。按 Esc 停止。')
        self.root.iconify()
        def worker():
            try:
                from pvp import run_loop
                run_loop(progress=lambda text:self.messages.put(('progress',text)))
            except Exception as exc:
                self.messages.put('全自动 PVP 已停止：'+str(exc))
        threading.Thread(target=worker,daemon=True).start()

    def stop_automatic(self):
        control.stop()
        self.set_status('已请求停止，正在结束当前输入。')

    def run_automatic(self,resume=False):
        control.reset()
        scope='visible'
        for button in self.action_buttons(): button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.scope_box.configure(state='disabled')
        self.set_status('全自动流程开始。按 Esc 可停止；切换窗口会停止操作。')
        self.root.iconify()
        def worker():
            try:
                from campaign import run_campaign
                report=run_campaign(progress=lambda text:self.messages.put(('progress',text)),scope=scope,
                                    resume_current=resume)
                self.messages.put(f"清理完成：共 {len(report['battles'])} 场，已确认检查范围内没有感染者。")
            except Exception as exc:
                self.messages.put('全自动停止：'+str(exc))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            text = self.messages.get_nowait()
            if isinstance(text,tuple):
                self.set_status(text[1])
                self.root.after(100,self.poll)
                return
            self.root.deiconify()
            self.set_status(text)
            self.scan.configure(state='normal'); self.enter.configure(state='normal')
            self.deploy_button.configure(state='normal')
            self.combat_button.configure(state='normal')
            self.settlement_button.configure(state='normal')
            self.auto_button.configure(state='normal')
            self.pvp_button.configure(state='normal')
            self.stop_button.configure(state='disabled')
            self.scope_box.configure(state='readonly')
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', action='store_true')
    parser.add_argument('--enter', action='store_true')
    parser.add_argument('--replace-gui', action='store_true')
    parser.add_argument('--auto',action='store_true')
    parser.add_argument('--scope',choices=('world','visible'),default='visible')
    parser.add_argument('--resume',action='store_true')
    args = parser.parse_args()
    if args.scan or args.enter:
        print(json.dumps(encounter(args.enter), ensure_ascii=False))
    else:
        if args.replace_gui:
            close_existing_gui()
        instance=App()
        instance.scope_var.set('当前可见地图（不拖动）')
        if args.auto: instance.root.after(300,lambda:instance.run_automatic(args.resume))
        instance.root.mainloop()
