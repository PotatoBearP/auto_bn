"""Calibrated, one-action combat controller. Never uses anti-air skill 3."""
import argparse
import json
import time
from functools import lru_cache
from PIL import ImageGrab, Image, ImageChops, ImageStat
import app
import mouse_backend as mouse
import control
import formation
import target_priority
import turn_watchdog
from unit_ai import get as unit_ai
from settlement import phase as settlement_phase

from paths import COMBAT, TEMPLATES
ROOT=COMBAT
PLAYERS=[(489,335),(709,445)]
SKILLS=unit_ai('heavy_gunner').skill_points

class BattleEnded(RuntimeError):
    def __init__(self,image):
        self.image=image
        super().__init__('战斗已进入结算。')

class CombatRetry(RuntimeError):
    """Transient combat observation failure; rebuild from a fresh frame."""

class TurnChanged(CombatRetry):
    """An animation took over before input; rebuild the next turn's decision."""

class AimUnavailable(CombatRetry):
    """Targeting failed while the turn and skill were still available."""

def wait_reticle(capture,timeout=6,reselect=None,skill=2,cooldown_reader=None):
    """Observe cooldown/turn changes, and recover a missing targeting overlay."""
    deadline=time.monotonic()+timeout
    retries=0
    while True:
        frame=capture()
        if not skill_panel_visible(frame):
            _,turn=wait_our_turn(capture,timeout=25)
            if not turn.get('our_turn'):
                raise CombatRetry('等待战斗动画及我方 UI 返回超时。')
            raise TurnChanged('已进入下一回合，需要重新分析技能。')
        reader=cooldown_reader or cooldown
        if reader(frame,skill,read_turns=False)['blocked']:
            raise TurnChanged(f'第 {skill} 技能已进入冷却，重新分析当前回合。')
        try:
            return reticle_center(frame)
        except RuntimeError:
            if time.monotonic()>=deadline:
                frame.save(ROOT/'reticle-unrecognized.png')
                if reselect is not None and retries<2:
                    reselect();retries+=1
                    deadline=time.monotonic()+4
                    continue
                raise AimUnavailable(f'第 {skill} 技能瞄准中心暂未识别，已等待并重选技能。')
            time.sleep(.2)

def reset_battle_state():
    import battle_model
    battle_model.reset()
    (ROOT/'battle-state.json').write_text('{"initial": true}',encoding='utf-8')
    (ROOT/'ally-state.json').unlink(missing_ok=True)


def observe_allies(image,controllers):
    """Observe current survivors, without permanently marking an unseen unit dead."""
    checked=any(getattr(ai,'check_survival',False) for ai in controllers.values())
    bars=[bar for bar in health_bars(image) if bar['side']=='friendly'] if checked else []
    available={};observations=[]
    for point,ai in controllers.items():
        requires_check=getattr(ai,'check_survival',False)
        body=requires_check and ai.present(image,point)
        selected=requires_check and ai.selected_at(image,point)
        bar=next((bar for bar in bars if abs(bar['foot'][0]-point[0])<35 and
                  abs(bar['foot'][1]-point[1])<15 and bar['hp_fraction']>0),None)
        alive=not requires_check or body or selected or bar is not None
        observations.append({'unit':list(point),'unit_id':ai.id,
                             'status':'observed' if alive else 'unseen',
                             'body_seen':bool(body),'selected_seen':bool(selected),
                             'hp_fraction':bar['hp_fraction'] if bar is not None else None})
        if alive: available[point]=ai
    return available,observations


def wait_selected_unit(capture,ai,player,attempts=10):
    """A click is asynchronous: do not read the previous unit's skill panel."""
    for _ in range(attempts):
        frame=capture()
        if not skill_panel_visible(frame):
            raise TurnChanged('切换单位期间回合改变，重新建模。')
        if not getattr(ai,'check_survival',False): return frame
        if ai.selected_at(frame,player):
            # The body highlight can precede the new skill panel by a frame.
            time.sleep(.15)
            frame=capture()
            if not skill_panel_visible(frame):
                raise TurnChanged('切换单位期间回合改变，重新建模。')
            if ai.selected_at(frame,player): return frame
        time.sleep(.12)
    return None

@lru_cache(maxsize=2)
def enemy_templates(include_air=False):
    templates=[]
    for path in sorted(TEMPLATES.glob('enemy-*.png')):
        if path.stem.split('-')[1]=='flyer' and not include_air: continue
        with Image.open(path) as reference:
            templates.append((path.stem.split('-')[1],reference.convert('RGB').resize((22,20))))
    return templates


SHAPE_BOUNDS={'artillery':(-90,-130,90,25),'antiair':(-90,-150,90,20),
              'veteran':(-50,-110,50,15),'armoredcar':(-60,-80,60,20),
              'rocketteam':(-85,-100,85,65),'crew':(-45,-95,45,15)}


@lru_cache(maxsize=8)
def shape_template(name):
    references=[]
    for path in TEMPLATES.glob(f'shape-{name}*.png'):
        with Image.open(path) as source:
            references.append(source.convert('RGB').resize((36,34)))
    return references


def shape_matches(image,name,x,y):
    if name not in SHAPE_BOUNDS: return True
    left,top,right,bottom=SHAPE_BOUNDS[name]
    sample=image.crop((x+left,y+top,x+right,y+bottom)).convert('RGB').resize((36,34))
    colors=list(sample.getdata())
    for reference in shape_template(name):
        reference_colors=list(reference.getdata())
        red_offsets=[i for i,(r,g,b) in enumerate(reference_colors) if r>120 and r>g*1.6 and r>b*1.6]
        if red_offsets:
            def nearby_red(index):
                px=index%36;py=index//36
                for sy in range(max(0,py-1),min(34,py+2)):
                    for sx in range(max(0,px-1),min(36,px+2)):
                        r,g,b=colors[sy*36+sx]
                        if r>100 and r>g*1.4 and r>b*1.4: return True
                return False
            red_matches=sum(nearby_red(i) for i in red_offsets)
            if red_matches<max(2,len(red_offsets)*.45): continue
        offsets=[i for i,(r,g,b) in enumerate(reference_colors)
                 if (r>120 and r>g*1.6 and r>b*1.6) or
                    (r>160 and g>100 and b<100) or 20<max(r,g,b)<70]
        if not offsets: continue
        difference=sum(sum(abs(a-b) for a,b in zip(colors[i],reference_colors[i])) for i in offsets)/(3*len(offsets))
        full_difference=sum(ImageStat.Stat(ImageChops.difference(sample,reference)).mean)/3
        if difference<42 or full_difference<34: return True
    return False

def initial_enemies(image,tracked=None,include_air=False):
    """Recognize visible infected sprites on the calibrated board, not empty cells."""
    templates=enemy_templates(include_air)
    found=[]
    for row in (1,2,3):
        for column in (range(2,5) if row==3 else range(1,6)):
            x=544+110*(row+column-2); y=196+55*(column-row)
            allowed={name:shape_matches(image,name,x,y) for name in {name for name,_ in templates}}
            eligible=[(name,reference) for name,reference in templates if allowed[name]]
            best=(999,None,None)
            for dy in (-4,0,4):
                for dx in (-4,0,4):
                    sample=image.crop((x+dx-22,y+dy-55,x+dx+22,y+dy-15)).convert('RGB').resize((22,20))
                    for name,reference in eligible:
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
    if target_priority.ATTRITION.get():
        import attrition_vision
        observed=attrition_vision.enemies(image,include_air=True)
        ignored={(e['row'],e['column']) for e in observed if e['sprite']=='airflyer'}
        visible=[e for e in observed if e['sprite']!='airflyer']
        from battle_rules import CELLS,position
        obstacles={cell for cell in CELLS if attrition_vision.obstacle_at(image,position(cell))}
        state['ignored_obstacles']=[{'row':r,'column':c,'kind':'obstacle'} for r,c in sorted(obstacles)]
        bars=[bar for bar in bars if (bar['row'],bar['column']) not in ignored and
              (bar['row'],bar['column']) not in obstacles and not attrition_vision.obstacle_at(image,bar['foot'])]
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
    enemies=[e for e in enemies if not target_priority.is_obstacle(e)]
    enemies=target_priority.annotate(enemies,previous,state)
    if target_priority.ATTRITION.get():
        for enemy in enemies: enemy['high_value_target']=target_priority.high_value(enemy)
    state['last_enemies']=enemies
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
    friendly=formation.friendly_positions()
    scan_left=max(0,min([400]+[p[0]-50 for p in friendly]))
    scan_bottom=min(image.height-20,max([540]+[p[1]+50 for p in friendly]))
    for y in range(110,scan_bottom):
        x=scan_left
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
            if any(abs(foot[0]-p[0])<45 and abs(foot[1]-p[1])<15 for p in friendly): side='friendly'
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
        yellow_threshold=150 if enemy.get('sprite')=='antiair' else 45
        if green>25 or yellow>yellow_threshold:
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
    return unit_ai('heavy_gunner').hits(image,enemies,skill)

def sweep_targets(enemies):
    """Aim once per column at its front unit, highest remaining HP first."""
    return unit_ai('heavy_gunner').targets(enemies,2)

def _combat_step(preview_only=False,force_skill=None,context=None):
    """Observe -> pure model planning -> execute exactly one chosen action."""
    from combat_planner import plan
    from battle_rules import validate_models
    controllers=dict(formation.units())
    if not controllers: raise RuntimeError('阵型中没有可操作的 AI 单位。')
    for ai in controllers.values(): validate_models(ai)
    hwnd=app.find_game()
    if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
    app.focus_game(hwnd);box=app.bounds(hwnd)
    if abs(box[2]-box[0]-1366)>2 or abs(box[3]-box[1]-768)>2:
        raise RuntimeError('战斗识别适用于约 1366×768。')
    metrics={'gui_range_scans':0,'skill_selections':0,'aim_drags':0,'unit_selections':0}
    def check():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，已停止战斗操作。')
    def capture():
        check();frame=ImageGrab.grab(bbox=box,all_screens=True)
        if settlement_phase(frame) in ('loot','experience'): raise BattleEnded(frame)
        turn_watchdog.observe(frame)
        return frame
    def click(point):
        frame=capture()
        if not skill_panel_visible(frame): raise TurnChanged('回合动画进行中，等待后重新建模。')
        mouse.click(box[0]+point[0],box[1]+point[1]);time.sleep(.12)
    def select(player):
        turn_watchdog.event('select_unit',{'selecting_unit':list(player)})
        click(player);metrics['unit_selections']+=1
        return wait_selected_unit(capture,controllers[player],player)
    def attrition_pass(reason,allies):
        report={'released':False,'action':'skip_turn','reason':reason,
                'skipped':False,'allies':allies}
        if context is not None: context['report']=report
        if not preview_only:
            from pvp import pass_available
            if not pass_available(capture()): raise CombatRetry('放弃按钮暂不可用，等待后重新检查。')
            click((70,203));report['skipped']=True
            after,turn=wait_our_turn(capture,require_transition=True)
            report.update(settled=turn['our_turn'],turn_observation=turn,
                          skip_confirmed=bool(turn['our_turn'] and turn.get('opponent_ui_disappearance_seen')))
        (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    turn_watchdog.event('wait_our_turn')
    if target_priority.ATTRITION.get():
        frame=capture()
        if not skill_panel_visible(frame):
            # A selected coward's death can leave no panel at all. Selecting a
            # freshly observed survivor restores it; waiting alone never will.
            survivors,_=observe_allies(frame,controllers)
            if survivors:
                player=next(iter(survivors))
                check();mouse.click(box[0]+player[0],box[1]+player[1]);time.sleep(.15)
    image,turn=wait_our_turn(capture)
    if not turn['our_turn']: raise CombatRetry('等待我方回合稳定，未发送技能。')
    configured=controllers
    controllers,allies=observe_allies(image,configured)
    if len(controllers)<len(configured):
        time.sleep(.15);image=capture()
        if not skill_panel_visible(image): raise TurnChanged('存活观察期间回合改变。')
        controllers,allies=observe_allies(image,configured)
    (ROOT/'ally-state.json').write_text(json.dumps(allies,ensure_ascii=False,indent=2),encoding='utf-8')
    if not controllers: raise CombatRetry('暂未看到存活单位，等待结算或重新观察。')
    ally_health={tuple(ally['unit']):ally['hp_fraction'] for ally in allies}
    if target_priority.ATTRITION.get():
        from combat_planner import health_fraction
        controllers=dict(sorted(controllers.items(),key=lambda item:health_fraction(ally_health.get(item[0]))))
    image.save(ROOT/'combat-before.png')
    if target_priority.ATTRITION.get() and force_skill is None:
        no_skills=True
        for player,ai in controllers.items():
            selected=select(player)
            if selected is None: raise CombatRetry('检查剩余技能时单位暂不可选。')
            if any(not ai.cooldown(selected,k,read_turns=False)['blocked'] for k in ai.skill_order):
                no_skills=False;break
        if no_skills:
            return attrition_pass('all_survivors_no_skills',allies)
    enemies=observe_enemies(image)
    if not enemies and target_priority.ATTRITION.get():
        import attrition_vision
        if any(e['sprite']=='airflyer' for e in attrition_vision.enemies(image,include_air=True)):
            return attrition_pass('only_untargetable_air_units',allies)
    if not enemies:
        deadline=time.monotonic()+6
        while time.monotonic()<deadline and not enemies:
            time.sleep(.2);image=capture();enemies=observe_enemies(image)
        if not enemies: raise CombatRetry('敌方阵容暂未识别，等待后重新建模。')
    priority_mode=target_priority.enabled(enemies)
    if priority_mode and all(target_priority.level(e)==0 for e in enemies):
        state_path=ROOT/'battle-state.json'
        state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        if any(target_priority.level(e)>0 for e in state.get('missing_vehicles',[])):
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                time.sleep(.2);image=capture();fresh=observe_enemies(image)
                if fresh: enemies=fresh
                if any(target_priority.level(e)>0 for e in enemies): break
    import battle_model
    battle_model.update(image,enemies)
    turn_watchdog.event('modeling',{'enemies':enemies,'allies':allies})
    skills_for={player:(ai.available_skills(enemies) if hasattr(ai,'available_skills') else ai.skill_order)
                for player,ai in controllers.items()}
    started=time.perf_counter()
    candidates=plan(controllers,enemies,skills_for,force_skill,ally_health=ally_health)
    metrics['planning_ms']=round((time.perf_counter()-started)*1000,3)
    metrics['modeled_candidates']=len(candidates)
    report={'enemies':enemies,'allies':allies,'cooldowns':[],'options':[],
            'planned_options':candidates,'planning_mode':'model_first','metrics':metrics,
            'released':False,'decision_completed_before_skill_input':True,
            'strategy':('wounded_coward_then_coverage_then_high_value_then_finishing' if target_priority.ATTRITION.get() else
                        'threat_then_existing_strategy' if priority_mode else 'modeled_coverage_and_health'),
            'model':'declarative_553_skill_models'}
    if context is not None: context['report']=report
    turn_watchdog.event('select_action',{'current_combat_report':report})
    checked={};unavailable=set();selected_player=None;chosen=None
    for candidate in candidates:
        player=tuple(candidate['unit']);ai=controllers[player];skill=candidate['skill']
        if player in unavailable: continue
        if player not in checked:
            selected=select(player);selected_player=player
            if selected is None:
                unavailable.add(player);continue
            checked[player]={k:ai.cooldown(selected,k,read_turns=False) for k in skills_for[player]}
            report['cooldowns'].append({'unit':list(player),'unit_id':ai.id,'skills':checked[player]})
        if checked[player][skill]['blocked']: continue
        if selected_player!=player:
            selected=select(player);selected_player=player
            if selected is None: unavailable.add(player);continue
        chosen=candidate;break
    for ally in allies:
        if tuple(ally['unit']) in unavailable: ally['status']='unselectable'
    (ROOT/'ally-state.json').write_text(json.dumps(allies,ensure_ascii=False,indent=2),encoding='utf-8')
    if chosen is None:
        remaining=[p for p in controllers if p not in unavailable]
        if not remaining: raise CombatRetry('单位暂不可选，重新读取存活阵容。')
        # A lack of modeled reachable targets is not an instruction to pass.
        blocked=(force_skill is None and all(p in checked and all(checked[p][k]['blocked']
                    for k in skills_for[p]) for p in remaining))
        if not blocked:
            if target_priority.ATTRITION.get() and not unavailable:
                return attrition_pass('no_reachable_ready_skill',allies)
            raise CombatRetry('暂未找到可执行的建模方案，重新观察。')
        report.update(action='skip_turn',skipped=False)
        if not preview_only:
            for player in remaining:
                frame=select(player)
                if frame is None: raise CombatRetry('等待回合前单位状态改变，重新建模。')
                ai=controllers[player]
                if not all(ai.cooldown(frame,k,read_turns=False)['blocked'] for k in skills_for[player]):
                    raise CombatRetry('技能已恢复，重新计算攻击。')
            click((70,203));report['skipped']=True
            after,turn=wait_our_turn(capture,require_transition=True)
            report.update(settled=turn['our_turn'],turn_observation=turn,
                          skip_confirmed=bool(turn['our_turn'] and turn.get('opponent_ui_disappearance_seen')))
            if turn['our_turn']: battle_model.update(after,advance=True)
        (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    player=tuple(chosen['unit']);ai=controllers[player];skill=chosen['skill']
    # This is state validation, never a range scan or candidate evaluation.
    frame=capture()
    if getattr(ai,'check_survival',False) and not ai.selected_at(frame,player):
        raise CombatRetry('执行前单位状态改变，重新建模。')
    if ai.cooldown(frame,skill,read_turns=False)['blocked']:
        raise CombatRetry('执行前技能状态改变，重新建模。')
    if priority_mode and chosen['priority_key'][0]==0:
        fresh=observe_enemies(frame)
        if target_priority.new_threat_before_cleanup(enemies,fresh):
            raise CombatRetry('新乘员出现，重新计算威胁优先级。')
    report['chosen']=chosen;report['options']=[chosen]
    if preview_only:
        (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    turn_watchdog.event('select_skill',{'chosen':chosen})
    click(ai.skill_points[skill]);metrics['skill_selections']+=1
    target=tuple(chosen['target'])
    if chosen['aiming']=='drag':
        turn_watchdog.event('aim_at_planned_target')
        def reselect():
            click(ai.skill_points[skill])
        origin=ai.locate_aim(capture,reselect=reselect,skill=skill)
        if abs(origin[0]-target[0])>3 or abs(origin[1]-target[1])>3:
            mouse.drag((box[0]+origin[0],box[1]+origin[1]),
                       (box[0]+target[0],box[1]+target[1]),check)
            metrics['aim_drags']+=1
        time.sleep(ai.aim_settle_seconds)
        confirm=ai.locate_aim(capture,skill=skill)
        if abs(confirm[0]-target[0])>20 or abs(confirm[1]-target[1])>15:
            raise CombatRetry('瞄准圈未到达计算落点，重试执行。')
    else:
        time.sleep(ai.aim_settle_seconds);confirm=target
    frame=capture()
    if getattr(ai,'check_survival',False) and not ai.selected_at(frame,player):
        raise CombatRetry('释放前单位状态改变，重新建模。')
    before_signature=tuple((b['left'],b['top'],round(b['hp_fraction'],2)) for b in health_bars(frame))
    frame.save(ROOT/'combat-chosen-preview.png')
    report['confirmation_center']=list(confirm)
    turn_watchdog.event('confirm_attack',{'confirmation_center':list(confirm)})
    click(confirm);report['released']=True
    path=ROOT/'battle-state.json'
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    state['initial']=False;path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    turn_watchdog.event('wait_next_turn')
    after,turn=wait_our_turn(capture,require_transition=True,before_signature=before_signature)
    after.save(ROOT/'combat-after.png')
    report.update(turn_observation=turn,settled=turn['our_turn'],
                  battle_ended=turn.get('battle_ended',False),after_health_bars=health_bars(after))
    report['release_evidence']=release_evidence(after,skill,turn,policy=ai)
    report['release_confirmed']=bool(report['release_evidence'])
    if turn['our_turn'] and report['release_confirmed']: battle_model.update(after,advance=True)
    (ROOT/'combat-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def release_evidence(image,skill,turn,policy=None):
    if turn.get('battle_ended'): return 'settlement'
    if turn.get('our_turn'):
        transition=turn.get('opponent_ui_disappearance_seen')
        health_change=turn.get('health_change_seen')
        if transition and health_change: return 'turn_transition_and_health_change'
        # wait_our_turn already requires the returning panel to settle, or a
        # changed health signature to stay stable when a fast turn is missed.
        # The next selected unit's ready icon cannot invalidate that evidence.
        if transition: return 'turn_transition'
        if health_change: return 'settled_health_change'
    reader=policy.cooldown if policy else cooldown
    if reader(image,skill,read_turns=False)['blocked']: return 'cooldown'
    return None

def combat_step(preview_only=False,force_skill=None):
    context={}
    try:
        for attempt in range(4):
            try:
                return _combat_step(preview_only,force_skill,context)
            except TurnChanged:
                # Never reuse old aim coordinates after a turn transition.
                if context.get('report',{}).get('released'): raise
                context.clear()
        raise CombatRetry('连续四次分析时回合发生改变，等待后重新分析。')
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
