"""Pure 5/5/3 geometry. Skill definitions are mandatory for every unit."""
from dataclasses import dataclass

CELLS=tuple((row,col) for row in (1,2,3)
            for col in (range(2,5) if row==3 else range(1,6)))


def position(cell):
    row,col=cell
    return (544+110*(row+col-2),196+55*(col-row))


def enemy_cell(enemy):
    if 'row' in enemy and 'column' in enemy: return enemy['row'],enemy['column']
    x,y=enemy['foot'];dx=(x-544)/110;dy=(y-196)/55
    return round((dx-dy)/2)+1,round((dx+dy)/2)+1


@dataclass(frozen=True)
class SkillModel:
    aiming: str
    anchors: str='board'
    main: tuple=((0,0),)
    splash: tuple=()
    absolute: bool=False
    excluded_types: tuple=()
    require_full: bool=False

    def legal_anchors(self,enemies):
        if self.anchors=='front': anchors=tuple(cell for cell in CELLS if cell[0]==1)
        elif self.anchors=='occupied':
            anchors=tuple(dict.fromkeys(enemy_cell(e) for e in enemies if enemy_cell(e) in CELLS and
                                       e.get('sprite') not in self.excluded_types and
                                       (not self.absolute or enemy_cell(e) in self.main)))
        elif self.anchors=='board': anchors=CELLS
        else: raise ValueError(f'未知瞄准格规则：{self.anchors}')
        if self.require_full:
            anchors=tuple(anchor for anchor in anchors if all(
                (offset if self.absolute else (anchor[0]+offset[0],anchor[1]+offset[1])) in CELLS
                for offset in self.main+self.splash))
        return anchors

    def coverage(self,anchor):
        def cells(offsets):
            return {offset if self.absolute else (anchor[0]+offset[0],anchor[1]+offset[1])
                    for offset in offsets}&set(CELLS)
        main=cells(self.main)
        return main,cells(self.splash)-main

    def predict(self,enemies,anchor):
        main,splash=self.coverage(anchor);hits=[]
        for enemy in enemies:
            if enemy.get('sprite') in self.excluded_types: continue
            cell=enemy_cell(enemy)
            if cell in main or cell in splash:
                hits.append({**enemy,'damage_band':'main' if cell in main else 'splash'})
        return hits


def validate_models(ai):
    models=getattr(ai,'skill_models',None)
    if not models or set(models)!=set(ai.skill_order):
        raise ValueError(f'{ai.name}必须为每个自动战斗技能提供 SkillModel，禁止范围试探回退。')
    for skill,model in models.items():
        if not isinstance(model,SkillModel) or model.aiming not in ('drag','direct'):
            raise ValueError(f'{ai.name}技能 {skill} 模型无效。')
        if (skill in ai.drag_skills)!=(model.aiming=='drag'):
            raise ValueError(f'{ai.name}技能 {skill} 的瞄准方式与模型不一致。')
        model.legal_anchors([])
