"""Elite boxer: front row, draggable single target, and staggered cross."""
from functools import lru_cache
from PIL import Image,ImageChops,ImageStat
from paths import TEMPLATES
from battle_rules import SkillModel,CELLS


@lru_cache(maxsize=1)
def body_reference():
    with Image.open(TEMPLATES/'elite-boxer-body.png') as source:
        return source.convert('RGB').resize((22,30))


class EliteBoxerAI:
    id='elite_boxer'
    name='顶尖拳击手'
    icon_template='elite-boxer-icon.png'
    skill_order=(3,1,2)
    skill_points={1:(300,721),2:(404,721),3:(508,721)}
    drag_skills=(1,2,3)
    skill_priority={3:1}
    aim_settle_seconds=.4
    allowed_rows=(1,)
    check_survival=True
    skill_models={
        1:SkillModel('drag',absolute=True,main=tuple((1,c) for c in range(1,6)),
                     anchor_cells=((1,3),(1,2),(1,4),(1,1),(1,5)),excluded_types=('airflyer',)),
        2:SkillModel('drag','occupied',excluded_types=('airflyer',)),
        3:SkillModel('drag',main=((0,0),(-2,0),(2,0),(0,-2),(0,2),
                                 (-1,-1),(-1,1),(1,-1),(1,1)),
                     anchor_cells=tuple(dict.fromkeys(((2,3),(1,3),(1,1))+CELLS)),excluded_types=('airflyer',)),
    }

    def selected_at(self,image,cell):
        x,y=cell
        colors=image.convert('RGB').crop((x-35,y-85,x+40,y-12)).getdata()
        return sum(r<110 and 55<g<195 and b>160 and b>g*1.3 and b>r*1.7
                   for r,g,b in colors)>30

    def present(self,image,cell):
        x,y=cell
        for dy in (-4,0,4):
            for dx in (-4,0,4):
                sample=image.crop((x-22+dx,y-70+dy,x+22+dx,y-10+dy)).convert('RGB').resize((22,30))
                if sum(ImageStat.Stat(ImageChops.difference(sample,body_reference())).mean)/3<30:
                    return True
        return False

    def cooldown(self,image,skill,read_turns=False):
        from combat import cooldown
        return cooldown(image,skill,read_turns=read_turns)

    def locate_aim(self,capture,reselect=None,skill=3):
        from combat import wait_reticle
        return wait_reticle(capture,reselect=reselect,skill=skill,cooldown_reader=self.cooldown)

    def evaluate(self,hits,skill):
        return hits,float(len(hits))+.1*sum(1-e.get('hp_fraction',1.) for e in hits)
