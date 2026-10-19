"""Persistent 5/5/3 PVE formation and the formation deployed in the current battle."""
import json
from paths import PROJECT, COMBAT
from unit_ai import get

CONFIG_PATH = PROJECT/'config'/'formation.json'
SWEEP_PATH = PROJECT/'config'/'sweep-formation.json'
ACTIVE_PATH = COMBAT/'active-formation.json'
ROWS = (5, 5, 3)

def cells():
    return [(row, column) for row, count in enumerate(ROWS, 1) for column in range(1, count+1)]

def position(row, column):
    if (row, column) not in cells(): raise ValueError('无效的 553 格子。')
    board_column = column+1 if row == 3 else column
    return ((378,489,599,709,819)[board_column-1]-110*(row-1),
            280+55*(board_column-1)+55*(row-1))

def defaults():
    return {'version':1, 'units':[{'row':1,'column':c,'unit':'heavy_gunner'} for c in (2,4)]}


def sweep_defaults():
    return {'version':1,'units':[{'row':1,'column':3,'unit':'heavy_gunner'}]}


def load_sweep():
    if not SWEEP_PATH.exists(): return sweep_defaults()
    return validate(json.loads(SWEEP_PATH.read_text(encoding='utf-8')))


def save_sweep(config):
    return save(config,path=SWEEP_PATH)

def validate(config):
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('阵型配置格式或版本不正确。')
    units=config.get('units')
    if not isinstance(units,list) or not units: raise ValueError('请至少选择一个有 AI 的单位。')
    used=set();clean=[]
    for unit in units:
        if not isinstance(unit,dict) or not {'row','column','unit'} <= unit.keys():
            raise ValueError('单位配置需要行、列和单位类型。')
        row,column=unit['row'],unit['column']
        if type(row) is not int or type(column) is not int:
            raise ValueError('行列编号必须是整数。')
        position(row,column);ai=get(unit['unit'])
        if row not in getattr(ai,'allowed_rows',(1,2,3)):
            raise ValueError(f'{ai.name}只能放在第一排攻击。')
        if (row,column) in used: raise ValueError('一个格子只能配置一个单位。')
        used.add((row,column));clean.append({'row':row,'column':column,'unit':unit['unit']})
    # Older configurations may contain an aircraft flag; ignore that removed option.
    return {'version':1,'units':sorted(clean,key=lambda u:(u['row'],u['column']))}

def load():
    if not CONFIG_PATH.exists(): return defaults()
    return validate(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))

def save(config,path=None):
    path=CONFIG_PATH if path is None else path
    config=validate(config);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)
    return config

def activate(config):
    ACTIVE_PATH.write_text(json.dumps(validate(config),ensure_ascii=False,indent=2),encoding='utf-8')

def active():
    if ACTIVE_PATH.exists(): return validate(json.loads(ACTIVE_PATH.read_text(encoding='utf-8')))
    return load()

def units(config=None):
    return [(position(u['row'],u['column']),get(u['unit'])) for u in (config or active())['units']]

def friendly_positions():
    return [cell for cell,_ in units(active())]
