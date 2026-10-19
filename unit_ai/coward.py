"""Coward: front-row aiming, three-cell lines, coverage plus low HP."""
from functools import lru_cache
from PIL import Image,ImageChops,ImageStat
from paths import TEMPLATES
import target_priority
from battle_rules import SkillModel


@lru_cache(maxsize=1)
def body_templates():
    templates=[]
    for path in TEMPLATES.glob('coward-body*.png'):
        with Image.open(path) as source:
            templates.append(source.convert('RGB').resize((22,30)))
    return templates


class CowardAI:
    id='coward'
    name='胆小鬼'
    icon_template='coward-icon.png'
    skill_order=(1,2)
    skill_points={1:(300,721),2:(404,721)}
    drag_skills=(1,2)
    aim_settle_seconds=.4
    allowed_rows=(1,)
    check_survival=True
    skill_models={
        1:SkillModel('drag','front',main=((0,0),(1,0),(2,0)),require_full=True),
        2:SkillModel('drag','front',main=((0,-1),(0,0),(0,1)),require_full=True),
    }

    def selected_at(self,image,cell):
        """The selected unit's blue body outline, excluding the ground diamond."""
        x,y=cell
        colors=image.convert('RGB').crop((x-35,y-85,x+40,y-12)).getdata()
        blue=sum(r<110 and 55<g<195 and b>160 and b>g*1.3 and b>r*1.7 for r,g,b in colors)
        return blue>30

    def present(self,image,cell):
        x,y=cell
        references=body_templates()
        for dy in (-4,0,4):
            for dx in (-4,0,4):
                sample=image.crop((x-22+dx,y-70+dy,x+22+dx,y-10+dy)).convert('RGB').resize((22,30))
                if any(sum(ImageStat.Stat(ImageChops.difference(sample,reference)).mean)/3<22 for reference in references):
                    return True
        return False

    def cooldown(self,image,skill,read_turns=False):
        from combat import cooldown
        return cooldown(image,skill,read_turns=read_turns)

    def locate_aim(self,capture,reselect=None,skill=1):
        from combat import wait_reticle
        return wait_reticle(capture,reselect=reselect,skill=skill,cooldown_reader=self.cooldown)

    def covered_cells(self,column,skill):
        return self.skill_models[skill].coverage((1,column))[0]

    def predicted_hits(self,enemies,column,skill):
        cells=self.covered_cells(column,skill)
        return [e for e in enemies if (e['row'],e['column']) in cells]

    def targets(self,enemies,skill):
        active=target_priority.enabled(enemies)
        ranked=sorted(range(1,6),key=lambda c:target_priority.attack_key(
            self.predicted_hits(enemies,c,skill),lambda hits:self.evaluate(hits,skill)[1],active),reverse=True)
        return [(544+110*(c-1),196+55*(c-1)) for c in ranked
                if self.predicted_hits(enemies,c,skill)]

    def max_score(self,enemies,skill):
        return max(self.evaluate(self.predicted_hits(enemies,c,skill),skill)[1] for c in range(1,6))

    def optimistic_key(self,enemies,skill):
        return max(target_priority.attack_key(self.predicted_hits(enemies,c,skill),
                   lambda hits:self.evaluate(hits,skill)[1]) for c in range(1,6))

    def hits(self,image,enemies,skill):
        from combat import area_hits,reticle_center,AimUnavailable
        try: x,y=reticle_center(image)
        except RuntimeError as exc: raise AimUnavailable('胆小鬼范围预览的瞄准圈暂未识别。') from exc
        column=round((x-544)/110)+1
        if not 1<=column<=5: return []
        if abs(x-(544+110*(column-1)))>25 or abs(y-(196+55*(column-1)))>20: return []
        cells=self.covered_cells(column,skill)
        return [e for e in area_hits(image,enemies) if (e['row'],e['column']) in cells]

    def evaluate(self,hits,skill):
        score=float(len(hits))
        for enemy in hits:
            # Unmeasured HP must not earn a low-health bonus.
            if enemy.get('hp_source')!='health_bar': continue
            hp=max(0.,min(1.,enemy.get('hp_fraction',1.)))
            score+=.75*(1-hp)+(.5 if hp<=.3 else 0.)
        return hits,score

    def confirmation_target(self,hits,skill,target):
        return tuple(target)
