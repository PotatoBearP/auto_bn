"""Threat ordering shared by recognition, previews and unit policies."""
HIGH=2
LOW=1
NONE=0
CATALOG={
    'artillery':{'name':'大型火炮','threat':HIGH,'kind':'vehicle'},
    'veteran':{'name':'老兵','threat':HIGH,'kind':'infantry'},
    'antiair':{'name':'防空炮','threat':NONE,'kind':'vehicle'},
    'armoredcar':{'name':'装甲车','threat':LOW,'kind':'vehicle'},
    'rocketteam':{'name':'火箭手','threat':LOW,'kind':'infantry'},
    'crew':{'name':'乘员','threat':LOW,'kind':'infantry'},
}
LABELS={HIGH:'高',LOW:'低',NONE:'无'}


def level(enemy):
    return CATALOG.get(enemy.get('sprite'),{}).get('threat',LOW)


def enabled(enemies):
    return any(e.get('priority_mode') or e.get('sprite') in CATALOG for e in enemies)


def attack_key(hits,evaluate,active=True):
    """No amount of lower-tier coverage outranks hitting a higher tier."""
    if not active: return (evaluate(hits),)
    highest=max((level(e) for e in hits),default=-1)
    return (highest,)+tuple(evaluate([e for e in hits if level(e)==tier])
                            for tier in (HIGH,LOW,NONE))


def new_threat_before_cleanup(before,after):
    return bool(before) and all(level(e)==NONE for e in before) and any(level(e)>NONE for e in after)


def annotate(enemies,previous,state):
    """Fresh visual type/HP only; identity changes must not resurrect a vehicle."""
    active=state.get('priority_mode',False) or enabled(enemies)
    state['priority_mode']=active
    next_id=state.get('next_enemy_id',1)
    # A vehicle can disappear before its passenger's animation becomes visible.
    missing=[{**p,'age':p.get('age',0)+1} for p in state.get('missing_vehicles',[]) if p.get('age',0)<8]
    for prior in previous:
        if CATALOG.get(prior.get('sprite'),{}).get('kind')!='vehicle': continue
        if any((e['row'],e['column'],e.get('sprite'))==
               (prior['row'],prior['column'],prior.get('sprite')) for e in enemies): continue
        if not any(p.get('entity_id')==prior.get('entity_id') for p in missing):
            missing.append({**prior,'age':0})
    used=set();events=[]
    for enemy in enemies:
        cell=(enemy['row'],enemy['column'])
        same_cell=next((p for p in previous if (p['row'],p['column'])==cell),None)
        if CATALOG.get(enemy.get('sprite'),{}).get('kind')=='infantry':
            vehicle=next((p for p in missing if (p['row'],p['column'])==cell),None)
            if vehicle and (same_cell is None or same_cell.get('sprite')!=enemy.get('sprite')):
                same_cell=vehicle
        candidates=[p for p in previous if p.get('entity_id') not in used and
                    p.get('sprite')==enemy.get('sprite') and p.get('entity_id') is not None and
                    (p['row'],p['column'])==cell]
        # A surviving unit can advance within its column. Never carry HP along.
        if not candidates and enemy.get('sprite'):
            candidates=[p for p in previous if p.get('entity_id') not in used and
                        p.get('sprite')==enemy['sprite'] and p['column']==enemy['column'] and
                        p['row']>enemy['row'] and p.get('entity_id') is not None]
        if candidates:
            prior=min(candidates,key=lambda p:abs(p['row']-enemy['row']))
            enemy['entity_id']=prior['entity_id'];used.add(prior['entity_id'])
            for key in ('replacement_of','spawned_from_vehicle'):
                if key in prior: enemy[key]=prior[key]
        else:
            enemy['entity_id']=next_id;next_id+=1
            if same_cell and same_cell.get('sprite')!=enemy.get('sprite'):
                enemy['replacement_of']=same_cell.get('entity_id')
                vehicle=CATALOG.get(same_cell.get('sprite'),{}).get('kind')=='vehicle'
                infantry=CATALOG.get(enemy.get('sprite'),{}).get('kind')=='infantry'
                enemy['spawned_from_vehicle']=vehicle and infantry
                events.append({'event':'occupant_observed' if vehicle and infantry else 'unit_replaced',
                               'row':cell[0],'column':cell[1],'from':same_cell.get('sprite'),
                               'to':enemy.get('sprite'),'entity_id':enemy['entity_id']})
        if active:
            enemy.update(threat_level=level(enemy),threat=LABELS[level(enemy)],priority_mode=True)
    state['next_enemy_id']=next_id;state['enemy_events']=events
    occupied={(e['row'],e['column']) for e in enemies if e.get('sprite') in CATALOG}
    state['missing_vehicles']=[p for p in missing if (p['row'],p['column']) not in occupied]
    return enemies
