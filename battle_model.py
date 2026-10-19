"""Observable enemy 5/5/3 board, kept separate from action selection."""
import json
import time
import unicodedata
from pathlib import Path
from paths import COMBAT
from target_priority import CATALOG

NAMES={'infected':'感染者','brute':'巨兽','tank':'坦克','flyer':'飞行者',
       'raider':'持火把兵','scout':'持刀兵','mammoth':'猛犸'}
NAMES.update({key:value['name'] for key,value in CATALOG.items()})


def build(enemies,turn=1):
    """Local columns are 1..3 in row 3; board columns there are 2..4."""
    indexed={(e['row'],e['column']):e for e in enemies}
    cells=[]
    for row,count in enumerate((5,5,3),1):
        for column in range(1,count+1):
            board_column=column+1 if row==3 else column
            enemy=indexed.get((row,board_column))
            cell={'row':row,'column':column,'board_column':board_column,
                  'occupied':enemy is not None,'hp_fraction':None,'hp_source':None}
            if enemy is not None:
                source=enemy.get('hp_source','unknown')
                fraction=enemy.get('hp_fraction')
                cell.update(unit=enemy.get('sprite','unknown'),
                            hp_fraction=max(0.,min(1.,fraction)) if fraction is not None else None,
                            hp_source=source,estimated=source!='health_bar',
                            foot=enemy.get('foot'))
                for key in ('entity_id','threat_level','threat','replacement_of','spawned_from_vehicle'):
                    if key in enemy: cell[key]=enemy[key]
            cells.append(cell)
    return {'version':1,'turn':turn,'observed_at':time.time(),'shape':[5,5,3],
            'hp_unit':'fraction','cells':cells,'enemy_count':sum(c['occupied'] for c in cells)}


def render(model):
    lines=[f"敌方阵容 5 / 5 / 3 · 观测回合 {model['turn']} · {model['enemy_count']} 单位",
           '前排朝向我方；格号为每排从左到右。','']
    for row in (1,2,3):
        labels=[]
        for cell in model['cells']:
            if cell['row']!=row: continue
            if not cell['occupied']:
                label='空'
            else:
                hp=cell['hp_fraction']
                value='血量?' if hp is None else ('<1%' if 0<hp<.005 else f"{hp*100:.0f}%")+('~' if cell['estimated'] else '')
                label=NAMES.get(cell['unit'],'单位')+cell.get('threat','')+' '+value
            label=f"[{cell['column']}:{label}]"
            width=sum(2 if unicodedata.east_asian_width(char) in ('W','F') else 1 for char in label)
            labels.append(label+' '*max(0,18-width))
        lines.append(f'{row}排 '+(' '*19 if row==3 else '')+' '.join(labels))
    lines.extend(['','~ 表示估计值；无血条暂按满血估计。',
                  '空 = 当前画面未识别到单位；遮挡或新兵种可能漏检。',
                  '血量为血条比例，非绝对生命值；回合从开始观测计数。'])
    return '\n'.join(lines)


def record(enemies,advance=False):
    path=COMBAT/'enemy-board.json'
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    turn=previous['turn']+int(advance) if previous else 1
    model=build(enemies,turn)
    # Atomic replacement lets the viewer read while the battle worker writes.
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)
    (COMBAT/'enemy-board.txt').write_text(render(model),encoding='utf-8')
    if previous is None or advance:
        with (COMBAT/'enemy-turns.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(model,ensure_ascii=False)+'\n')
    return model


def reset():
    for name in ('enemy-board.json','enemy-board.txt','enemy-turns.jsonl'):
        (COMBAT/name).unlink(missing_ok=True)


def update(image,enemies=None,advance=False):
    import combat
    ground=combat.observe_enemies(image) if enemies is None else enemies
    # Air units belong to the model but do not change the existing ground-only AI.
    air=[e for e in combat.initial_enemies(image,include_air=True) if e.get('sprite')=='flyer']
    occupied={(e['row'],e['column']) for e in ground}
    return record(ground+[e for e in air if (e['row'],e['column']) not in occupied],advance)


def capture_current():
    """Read only: never focus a window or issue combat input."""
    from PIL import ImageGrab
    import app
    import combat
    hwnd=app.find_game()
    if app.user32.IsIconic(hwnd) or app.user32.GetForegroundWindow()!=hwnd:
        raise RuntimeError('请先让游戏窗口处于前台，避免读取遮挡画面。')
    image=ImageGrab.grab(bbox=app.bounds(hwnd),all_screens=True)
    if abs(image.width-1366)>2 or abs(image.height-768)>2:
        raise RuntimeError('阵容识别需要约 1366 × 768 的游戏画面。')
    if not combat.skill_panel_visible(image):
        raise RuntimeError('等待我方回合稳定后再读取阵容。')
    return image,combat.observe_enemies(image)


def viewer():
    """Independent passive monitor; updates even with the main tool minimized."""
    import tkinter as tk
    root=tk.Tk();root.title('敌方战场模型 · 5 / 5 / 3');root.geometry('840x330')
    text=tk.Text(root,font=('SimSun',12),padx=16,pady=16,wrap='none',
                 bg='#101824',fg='#d8e8f8')
    text.pack(fill='both',expand=True)
    previous=[None]
    def poll():
        path=COMBAT/'enemy-board.json'
        try:
            raw=path.read_text(encoding='utf-8') if path.exists() else ''
            if raw!=previous[0]:
                previous[0]=raw
                message=render(json.loads(raw)) if raw else '等待战斗回合观测…'
                text.configure(state='normal');text.delete('1.0','end');text.insert('end',message)
                text.configure(state='disabled')
        except (OSError,ValueError): pass
        root.after(300,poll)
    poll();root.mainloop()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--capture',action='store_true')
    parser.add_argument('--image',type=Path)
    args=parser.parse_args()
    if args.image:
        from PIL import Image
        import combat
        with Image.open(args.image) as image:
            print(render(update(image)))
    elif args.capture:
        image,enemies=capture_current();print(render(update(image,enemies)))
    else:
        viewer()
