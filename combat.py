"""Calibrated, one-action combat controller. Never uses anti-air skill 3."""
import argparse
import json
import time
from functools import lru_cache
from PIL import ImageGrab, Image, ImageChops, ImageStat
import app
import mouse_backend as mouse
import control
from settlement import phase as settlement_phase

from paths import COMBAT, TEMPLATES
ROOT=COMBAT
PLAYERS=[(489,335),(709,445)]
SKILLS={1:(300,721),2:(404,721)}

class BattleEnded(RuntimeError):
    def __init__(self,image):
        self.image=image
        super().__init__('战斗已进入结算。')

class TurnChanged(RuntimeError):
    """An animation took over before input; rebuild the next turn's decision."""

class AimUnavailable(RuntimeError):
    """Targeting failed while the turn and skill were still available."""

def wait_reticle(capture,timeout=6,reselect=None):
    """Observe cooldown/turn changes, and recover a missing targeting overlay."""
    deadline=time.monotonic()+timeout
    retries=0
    while True:
        frame=capture()
        if not skill_panel_visible(frame):
            _,turn=wait_our_turn(capture,timeout=25)
            if not turn.get('our_turn'):
                raise RuntimeError('等待战斗动画及我方 UI 返回超时。')
            raise TurnChanged('已进入下一回合，需要重新分析技能。')
        if cooldown(frame,2,read_turns=False)['blocked']:
            raise TurnChanged('二技能已进入冷却，瞄准圈已消失，重新分析当前回合。')
        try:
            return reticle_center(frame)
        except RuntimeError:
            if time.monotonic()>=deadline:
                frame.save(ROOT/'reticle-unrecognized.png')
                if reselect is not None and retries<2:
                    reselect();retries+=1
                    deadline=time.monotonic()+4
                    continue
                raise AimUnavailable('二技能瞄准中心暂未识别，已等待并重选技能。')
            time.sleep(.2)

def reset_battle_state():
    (ROOT/'battle-state.json').write_text('{"initial": true}',encoding='utf-8')

@lru_cache(maxsize=1)
def enemy_templates():
    templates=[]
    for path in sorted(TEMPLATES.glob('enemy-*.png')):
        with Image.open(path) as reference:
            templates.append((path.stem.split('-')[1],reference.convert('RGB').resize((22,20))))
    return templates

def initial_enemies(image,tracked=None):
    """Recognize visible infected sprites on the calibrated board, not empty cells."""
    templates=enemy_templates()
    found=[]
    for row in (1,2,3):
        for column in (range(2,5) if row==3 else range(1,6)):
            x=544+110*(row+column-2); y=196+55*(column-row)
            best=(999,None,None)
            for dy in (-4,0,4):
                for dx in (-4,0,4):
                    sample=image.crop((x+dx-22,y+dy-55,x+dx+22,y+dy-15)).convert('RGB').resize((22,20))
                    for name,reference in templates:
                        score=sum(ImageStat.Stat(ImageChops.difference(sample,reference)).mean)/3
                        if score<best[0]: best=(score,name,[x+dx,y+dy])
            # Highlighted outlines and advancing poses alter the sprite crop.
            # Relax only for a previously identified unit in the same column,
            # and only within the calibrated forward movement distance.
            tracked_match=any(p.get('sprite')==best[1] and p['column']==column and
                              p['row']>=row and abs(p['foot'][0]-best[2][0])<=235 and
                              abs(p['foot'][1]-best[2][1])<=120 for p in (tracked or []))
            highlighted_body=False
            if 24<=best[0]<28:
                bx,by=best[2]
                colors=list(image.crop((bx-22,by-55,bx+22,by-15)).convert('RGB').getdata())
                red=sum(r>140 and r>g*1.6 and r>b*1.6 for r,g,b in colors)
                dark=sum(max(r,g,b)<100 for r,g,b in colors)
                green=sum(g>180 and g>r*1.4 and g>b*1.4 for r,g,b in colors)
                highlighted_body=red>100 and dark>150 and green>15
            if best[0]<24 or (best[0]<32 and tracked_match) or highlighted_body:
                found.append({'foot':best[2],'side':'enemy','row':row,'column':column,
                              'hp_fraction':1.0,'hp_source':'initial_full','sprite':best[1]})
    return found

def observe_enemies(image):
    path=ROOT/'battle-state.json'
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'initial':True}
    bars=[{**b,'hp_source':'health_bar'} for b in health_bars(image) if b['side']=='enemy']
    previous=state.get('last_enemies',[])
    tracked=previous+state.get('initial_roster',[]) if not state.get('initial',False) else None
    visible=initial_enemies(image,tracked=tracked)
    if state.get('initial',False) and visible: state['initial_roster']=visible
    enemies=bars[:]
    for enemy in visible:
        matching=next((b for b in bars if abs(enemy['foot'][0]-b['foot'][0])<30 and
                       abs(enemy['foot'][1]-b['foot'][1])<20),None)
        if matching:
            matching['sprite']=enemy['sprite']
            continue
        enemy['hp_fraction']=1.0
        enemy['hp_source']='full_without_bar'
        enemies.append(enemy)
    if bars: state['initial']=False
    state.pop('known_health',None)
    if enemies: state['last_enemies']=enemies
    path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    return enemies

def skill_panel_visible(image):
    slots=0
    for x in (277,381,485):
        pixels=list(image.crop((x,699,x+48,747)).convert('RGB').getdata())
        dark=sum(max(r,g,b)<100 for r,g,b in pixels)
        red=sum(r>80 and r>g*2.5 and r>b*2.5 for r,g,b in pixels)
        slots+=dark>600 or red>600
    return slots>=2

def wait_our_turn(capture,require_transition=False,timeout=25,before_signature=None):
    """React to the returning panel; retain a longer health-only fallback."""
    deadline=time.monotonic()+timeout
    saw_hidden=False; visible_since=None; previous_signature=None; changed_after_attack=False
    latest=None
    while time.monotonic()<deadline:
        latest=capture()
        if settlement_phase(latest) in ('loot','experience'):
            return latest,{'our_turn':False,'battle_ended':True,
                           'opponent_ui_disappearance_seen':saw_hidden}
        visible=skill_panel_visible(latest)
        if not visible:
            saw_hidden=True; visible_since=None; previous_signature=None
        else:
            # A witnessed UI transition is stronger and cheaper than scanning HP.
            signature=None
            if require_transition and not saw_hidden:
                signature=tuple((b['left'],b['top'],round(b['hp_fraction'],2)) for b in health_bars(latest))
                if before_signature is not None and signature!=before_signature:
                    changed_after_attack=True
            if signature!=previous_signature:
                visible_since=time.monotonic(); previous_signature=signature
            elif visible_since is None:
                visible_since=time.monotonic()
            stable_delay=.15 if saw_hidden or not require_transition else .8
            if (saw_hidden or changed_after_attack or not require_transition) and time.monotonic()-visible_since>=stable_delay:
                return latest,{'our_turn':True,'opponent_ui_disappearance_seen':saw_hidden,
                               'health_change_seen':changed_after_attack}
        time.sleep(.06)
    return latest,{'our_turn':False,'opponent_ui_disappearance_seen':saw_hidden}

def cooldown(image,skill,read_turns=True):
    x=281 if skill==1 else 385
    pixels=list(image.convert('RGB').crop((x,701,x+3,704)).getdata())
    red=sum(r>80 and r>g*2.5 and r>b*2.5 for r,g,b in pixels)
    blocked=red>len(pixels)*.65
    turns=None
    if blocked and read_turns:
        sx,sy=SKILLS[skill]
        crop=image.crop((sx-12,sy-13,sx+12,sy+14)).resize((144,162)).convert('RGB')
        mask=Image.new('L',crop.size,255)
        mask.putdata([0 if r>180 and g>130 and b<130 else 255 for r,g,b in crop.getdata()])
        path=ROOT/f'cooldown-{skill}.png'; mask.save(path)
        text=''.join(w['Text'] for w in app.recognize(path,all_words=True))
        digits=''.join(c for c in text if c.isdigit())
        if digits: turns=int(digits)
    return {'blocked':blocked,'turns':turns}

def health_bars(image):
    rgb=image.convert('RGB'); pixels=rgb.load(); results=[]
    for y in range(110,540):
        x=400
        while x<1160:
            if max(pixels[x,y])>=32: x+=1; continue
            left=x
            while x<1160 and max(pixels[x,y])<32: x+=1
            if not 72<=x-left<=95: continue
            if any(abs(left-r['left'])<4 and abs(y-r['top'])<20 for r in results): continue
            interior=rgb.crop((left+3,y+3,x-3,y+12))
            green=sum(g>70 and g>r*1.4 and g>b*1.4 for r,g,b in interior.getdata())
            if green<5:
                # A living unit with ~1 HP can have no visible green fill.
                # Validate the black frame instead of discarding its bar.
                dark=sum(max(color)<90 and max(color)-min(color)<12 for color in interior.getdata())
                bottom=max(sum(max(pixels[bx,y+offset])<40 for bx in range(left+3,x-3))
                           for offset in (13,14,15,16))
                if dark<interior.width*interior.height*.75 or bottom<(x-left-6)*.9: continue
            foot=((left+x)//2,y-34)
            if any(abs(foot[0]-p[0])<45 and abs(foot[1]-p[1])<15 for p in PLAYERS): side='friendly'
            else: side='enemy'
            dx=(foot[0]-544)/110; dy=(foot[1]-196)/55
            row=round((dx-dy)/2)+1;column=round((dx+dy)/2)+1
            if side=='enemy':
                gx=544+110*(row+column-2);gy=196+55*(column-row)
                if row not in (1,2,3) or column not in range(1,6) or abs(gx-foot[0])>20 or abs(gy-foot[1])>15: continue
            results.append({'left':left,'top':y,'foot':list(foot),'side':side,
                            'row':row,'column':column,
                            'hp_fraction':round(green/max(1,interior.width*interior.height),3)})
    return results

def reticle_center(image,enemies=None):
    """Search the whole battlefield for the distinctive blue double aiming ring.

    The aim can remain on an empty tile after dragging or enemy advancement.
    Enemy positions therefore do not constrain this detector.
    """
    template=Image.open(TEMPLATES/'reticle-reference.png').convert('RGB')
    def blue(color):
        r,g,b=color
        return r<110 and 55<g<195 and b>160 and b>g*1.3 and b>r*1.7
    offsets=[(x-55,y-28) for y in range(0,56,3) for x in range(0,110,3)
             if blue(template.getpixel((x,y)))]
    width,height=image.size
    mask=bytes(blue(color) for color in image.convert('RGB').getdata())
    flat=[dy*width+dx for dx,dy in offsets]
    def score(cx,cy):
        center=cy*width+cx
        return sum(mask[center+offset] for offset in flat)/max(1,len(flat))
    # Coarse global search followed by pixel-level refinement. The mask ignores
    # bright cyan ground tiles and yellow splash tiles, unlike the aiming ring.
    candidates=[]
    for cy in range(90,min(550,height-29),4):
        for cx in range(260,min(1240,width-56),4):
            value=score(cx,cy)
            if value>=.35: candidates.append((value,cx,cy))
    candidates.sort(reverse=True)
    peaks=[]
    for value,cx,cy in candidates:
        if any(abs(cx-px)<25 and abs(cy-py)<18 for _,px,py in peaks): continue
        peaks.append((value,cx,cy))
        if len(peaks)>=6: break
    best=(0,None)
    for _,cx,cy in peaks:
        for y in range(cy-4,cy+5):
            for x in range(cx-4,cx+5):
                value=score(x,y)
                if value>best[0]: best=(value,(x,y))
    (ROOT/'reticle-detection.json').write_text(json.dumps(
        {'score':round(best[0],3),'center':best[1],'search':'whole_battlefield'},
        ensure_ascii=False,indent=2),encoding='utf-8')
    if best[0]<.55:
        raise RuntimeError('未可靠定位二技能蓝色瞄准中心，停止。')
    return best[1]


def outline_hits(image,enemies):
    hit=[]
    for enemy in enemies:
        x,y=enemy['foot']
        pixels=image.convert('RGB').crop((x-50,y-105,x+55,y-30)).getdata()
        green=yellow=0
        for r,g,b in pixels:
            green+=g>210 and r<90 and b<150
            yellow+=r>210 and g>190 and b<90
        if green>25 or yellow>45:
            hit.append({**enemy,'outline_green':green,'outline_yellow':yellow})
    return hit

def area_hits(image,enemies):
    """Skill 2 uses filled ground tiles; sprite outlines and aiming ring are irrelevant."""
    pixels=image.convert('RGB').load(); hits=[]
    for enemy in enemies:
        x=544+110*(enemy['row']+enemy['column']-2)
        y=196+55*(enemy['column']-enemy['row'])
        blue=yellow=total=0
        # The whole inner rim remains visible even when a brute and its HP bar
        # cover the lower half. Do not infer coverage from the aiming ring.
        for dy in range(-48,49,8):
            for dx in range(-100,101,10):
                distance=abs(dx)/110+abs(dy)/55
                if not .72<=distance<=.94: continue
                if not (0<=x+dx<image.width and 0<=y+dy<image.height): continue
                r,g,b=pixels[x+dx,y+dy]; total+=1
                blue+=g>190 and b>175 and r<g*.8 and b>r*1.15
                yellow+=r>170 and g>160 and b<120 and abs(r-g)<70
        coverage=max(blue,yellow)/max(1,total)
        if max(blue,yellow)>=8 and coverage>=.14:
            hits.append({**enemy,'damage_band':'main' if blue>yellow else 'splash',
                         'area_blue':blue,'area_yellow':yellow,'area_coverage':round(coverage,3)})
    return hits

def skill_hits(image,enemies,skill):
    return area_hits(image,enemies) if skill==2 else outline_hits(image,enemies)

def sweep_targets(enemies):
    """Aim once per column at its front unit, highest remaining HP first."""
    columns={}
    for enemy in enemies:
        x,y=enemy['foot']
        dx=(x-544)/110; dy=(y-196)/55
        column=enemy.get('column',round((dx+dy)/2)+1)
        row=enemy.get('row',round((dx-dy)/2)+1)
        columns.setdefault(column,[]).append((row,enemy))
    health={column:sum(max(0,e.get('hp_fraction',1.0)) for _,e in units)
            for column,units in columns.items()}
    ordered=sorted(columns,key=lambda c:(-health[c],
                   -.2*(health.get(c-1,0)+health.get(c+1,0)),c))
    return [tuple(min(columns[c],key=lambda item:item[0])[1]['foot']) for c in ordered]

def _combat_step(preview_only=False,force_skill=None,context=None):
    hwnd=app.find_game()
    if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
    app.focus_game(hwnd)
    box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('战斗识别暂适用于约 1366×768。')
    def check():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，已停止战斗操作。')
    def capture():
        check()
        frame=ImageGrab.grab(bbox=box,all_screens=True)
        if settlement_phase(frame) in ('loot','experience'):
            raise BattleEnded(frame)
        return frame
    def locate_reticle():
        def reselect():
            click(player)
            if cooldown(capture(),2,read_turns=False)['blocked']:
                raise TurnChanged('重选前二技能进入冷却，重新分析。')
            click(SKILLS[2]);time.sleep(.4)
        return wait_reticle(capture,reselect=reselect)
    def click(point):
        check()
        if not skill_panel_visible(capture()):
            _,turn=wait_our_turn(capture)
            if not turn.get('our_turn'): raise RuntimeError('等待我方 UI 返回超时。')
            raise TurnChanged('输入前回合改变，重新分析。')
        mouse.click(box[0]+point[0],box[1]+point[1]); time.sleep(.12)
    image,turn=wait_our_turn(capture)
    if turn.get('battle_ended'):
        return {'battle_ended':True,'released':False}
    if not turn['our_turn']: raise RuntimeError('等待我方技能 UI 稳定超时，未攻击。')
    image.save(ROOT/'combat-before.png')
    # The left button identifies combat and can pass a cooldown-only turn.
    header=image.crop((15,181,125,226)).resize((330,135)); path=ROOT/'combat-phase.png'; header.save(path)
    phase=''.join(w['Text'] for w in app.recognize(path,'zh-Hans-CN',True))
    if '放弃' not in phase: raise RuntimeError('未确认回合战斗界面，停止。')
    def recover_aim_turn():
        # Cancel the overlay and pass this turn only after both gunners/retries fail.
        click(PLAYERS[0]);time.sleep(.2)
        report={'released':False,'skipped':False,'action':'skip_turn',
                'recovery':'aim_unavailable'}
        if context is not None: context['report']=report
        click((70,203));report['skipped']=True
        frame,observation=wait_our_turn(capture,require_transition=True)
        report.update(turn_observation=observation,settled=observation['our_turn'],
                      battle_ended=observation.get('battle_ended',False),
                      skip_confirmed=bool(observation.get('opponent_ui_disappearance_seen') and observation['our_turn']))
        frame.save(ROOT/'combat-after.png')
        (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    if context is not None: context['recover_aim_turn']=recover_aim_turn
    enemies=observe_enemies(image)
    if not enemies:
        # Cancel an old targeting overlay before taking a fresh observation.
        click(PLAYERS[0])
        deadline=time.monotonic()+6
        while not enemies:
            image=capture()
            if not skill_panel_visible(image):
                raise TurnChanged('敌人识别期间进入动画，重新等待回合。')
            enemies=observe_enemies(image)
            if enemies: break
            if time.monotonic()>=deadline:
                image.save(ROOT/'combat-unrecognized.png')
                raise RuntimeError('等待动画并重新识别 6 秒后仍未定位敌人，已保存 combat-unrecognized.png。')
            time.sleep(.2)
    options=[]; states=[]; preferred=None; ready=None;aim_unavailable=False
    # Check skill 1 on both gunners first. Once it can hit, do not preview skill 2.
    for skill in (1,2):
        if force_skill is not None and skill!=force_skill: continue
        for player in PLAYERS:
            click(player)
            selected=capture()
            available=cooldown(selected,skill,read_turns=preview_only)
            state=next((s for s in states if s['unit']==list(player)),None)
            if state is None:
                state={'unit':list(player),'skills':{}};states.append(state)
            state['skills'][skill]=available
            if available['blocked']: continue
            click(SKILLS[skill])
            targets=sweep_targets(enemies) if skill==2 else [tuple(enemies[0]['foot'])]
            for index,target in enumerate(targets):
                if skill==2:
                    try:
                        origin=locate_reticle()
                    except AimUnavailable:
                        aim_unavailable=True
                        ready=None
                        break # Try the other gunner instead of ending automation.
                    if origin!=target:
                        mouse.drag((box[0]+origin[0],box[1]+origin[1]),
                                   (box[0]+target[0],box[1]+target[1]),check)
                time.sleep(.25); preview=capture()
                hits=skill_hits(preview,enemies,skill)
                main=[h for h in hits if skill==1 or h['damage_band']=='main']
                full=len(main)
                score=full+.2*(len(hits)-len(main))+sum(.1*(1-h['hp_fraction']) for h in main)
                if skill==1 and hits: target=tuple(hits[0]['foot'])
                option={'unit':list(player),'skill':skill,'target':list(target),
                                'hit_count':len(hits),'full_hits':full,'splash_hits':len(hits)-full,
                                'score':round(score,3),'hits':hits}
                options.append(option)
                ready=(list(player),skill,list(target))
                preview.save(ROOT/'combat-preview.png')
                if hits:
                    preferred=option
                    break
            if preferred: break
        if preferred: break
    viable=[option for option in options if option['hit_count']>0]
    if not viable:
        if aim_unavailable: raise AimUnavailable('两个机枪手的二技能瞄准均未恢复，跳过本回合后重试。')
        all_blocked=(force_skill is None and len(states)==len(PLAYERS) and
                     all(all(s['skills'].get(k,{}).get('blocked',False) for k in (1,2)) for s in states))
        if not all_blocked:
            raise RuntimeError('没有可靠的命中范围，停止；不将识别失败作为跳过回合的依据。')
        report={'enemies':enemies,'cooldowns':states,'options':options,
                'action':'skip_turn','released':False,'skipped':False}
        if context is not None: context['report']=report
        if not preview_only:
            # Recheck both labels and all four cooldowns immediately before passing.
            for player in PLAYERS:
                click(player)
                selected=capture()
                if not all(cooldown(selected,k,read_turns=False)['blocked'] for k in (1,2)):
                    raise RuntimeError('跳过前发现技能已可用，停止本次跳过。')
            frame=capture()
            frame.crop((15,181,125,226)).resize((330,135)).save(path)
            text=''.join(w['Text'] for w in app.recognize(path,'zh-Hans-CN',True))
            if '放弃' not in text: raise RuntimeError('未确认左侧放弃按钮，未跳过回合。')
            click((70,203))
            report['skipped']=True
            previous,turn=wait_our_turn(capture,require_transition=True)
            previous.save(ROOT/'combat-after.png')
            report['turn_observation']=turn
            report['settled']=turn['our_turn']
            report['battle_ended']=turn.get('battle_ended',False)
            report['skip_confirmed']=bool(turn.get('opponent_ui_disappearance_seen') and turn['our_turn'])
        (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    best=preferred or max(viable,key=lambda option:option['score'])
    report={'enemies':enemies,'cooldowns':states,'options':options,'chosen':best,
            'released':False,'strategy':'skill_1_first_then_front_of_highest_health_column',
            'model':'initial full health / health bars; skill 1 outlines; skill 2 blue main tiles + yellow splash tiles'}
    if context is not None: context['report']=report
    if not preview_only:
        already_selected=ready==(best['unit'],best['skill'],best['target'])
        if not already_selected: click(best['unit'])
        selected=capture()
        if cooldown(selected,best['skill'],read_turns=False)['blocked']: raise RuntimeError('释放前技能已进入冷却，停止。')
        if not already_selected: click(SKILLS[best['skill']])
        if best['skill']==2:
            origin=locate_reticle()
            if origin!=tuple(best['target']):
                mouse.drag((box[0]+origin[0],box[1]+origin[1]),
                           (box[0]+best['target'][0],box[1]+best['target'][1]),check)
        preview=capture(); preview.save(ROOT/'combat-chosen-preview.png')
        if not skill_hits(preview,enemies,best['skill']): raise RuntimeError('释放前没有可靠的命中范围，停止。')
        if best['skill']==2:
            # The game needs time to settle the dragged marker before a full click.
            time.sleep(.4)
            check()
            confirm=locate_reticle()
        else:
            confirm=best['target']
        report['confirmation_center']=list(confirm)
        before_signature=tuple((b['left'],b['top'],round(b['hp_fraction'],2)) for b in health_bars(capture()))
        click(confirm) # Skill 2 must be confirmed at the actual blue ring center.
        report['released']=True
        state_path=ROOT/'battle-state.json'
        state=json.loads(state_path.read_text(encoding='utf-8'))
        state['initial']=False
        state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        # No further input until opponent UI disappearance and our panel's return.
        previous,turn=wait_our_turn(capture,require_transition=True,before_signature=before_signature)
        previous.save(ROOT/'combat-after.png')
        report['turn_observation']=turn
        report['settled']=turn['our_turn']
        report['battle_ended']=turn.get('battle_ended',False)
        report['after_health_bars']=health_bars(previous)
        # The next turn may select the other gunner. Its ready icon says nothing
        # about the skill just fired by the previous unit.
        report['release_evidence']=release_evidence(previous,best['skill'],turn)
        report['release_confirmed']=bool(report['release_evidence'])
        if not report['release_confirmed']:
            # After a lethal shot the game can reset skill icons before showing
            # the victory dialog. Observe that transition without more input.
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                frame=capture()
                if settlement_phase(frame) in ('loot','experience'):
                    report['battle_ended']=True
                    report['release_confirmed']=True
                    frame.save(ROOT/'combat-after.png')
                    break
                time.sleep(.2)
    (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def release_evidence(image,skill,turn):
    if turn.get('battle_ended'): return 'settlement'
    if (turn.get('our_turn') and turn.get('opponent_ui_disappearance_seen')
            and turn.get('health_change_seen')):
        return 'turn_transition_and_health_change'
    if cooldown(image,skill,read_turns=False)['blocked']: return 'cooldown'
    return None

def combat_step(preview_only=False,force_skill=None):
    context={}
    try:
        for attempt in range(4):
            try:
                return _combat_step(preview_only,force_skill,context)
            except AimUnavailable:
                if preview_only or context.get('report',{}).get('released'): raise
                recovery=context.get('recover_aim_turn')
                if recovery is None: raise
                try:
                    return recovery()
                except TurnChanged:
                    context.clear()
            except TurnChanged:
                # Never reuse old aim coordinates after a turn transition.
                if context.get('report',{}).get('released'): raise
                context.clear()
        raise RuntimeError('连续四次分析时回合发生改变，停止输入。')
    except BattleEnded as ended:
        ended.image.save(ROOT/'combat-after.png')
        report=context.get('report',{'released':False})
        report['battle_ended']=True
        report['release_confirmed']=bool(report['released'])
        report['settlement_interrupt']=True
        (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--preview',action='store_true')
    parser.add_argument('--skill',type=int,choices=(1,2))
    args=parser.parse_args()
    print(json.dumps(combat_step(args.preview,args.skill),ensure_ascii=True))
