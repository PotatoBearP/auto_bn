"""Heavy gunner policy. Screen observation/input stay in the combat engine."""
from battle_rules import SkillModel
class HeavyGunnerAI:
    id = 'heavy_gunner'
    name = '重机枪手'
    icon_template = 'heavy-gunner-icon.png'
    skill_order = (1, 2)
    skill_points = {1: (300, 721), 2: (404, 721)}
    drag_skills = (2,)
    aim_settle_seconds = .4
    pvp_opening_skill = 1
    pvp_opening_target = (764,306)
    skill_models={
        1:SkillModel('direct','occupied',main=tuple((r,c) for r in (1,2) for c in range(1,6)),
                     absolute=True,excluded_types=('antiair',)),
        2:SkillModel('drag','board',main=((0,0),(1,0),(2,0)),
                     splash=tuple((r,c) for r in (0,1,2) for c in (-1,1))),
    }

    def available_skills(self,enemies):
        # The cannon emplacement is not a valid bullet-sweep target.
        if enemies and all(e.get('sprite')=='antiair' for e in enemies): return (2,)
        return self.skill_order

    def locate_aim(self,capture,reselect=None,skill=2):
        from combat import wait_reticle
        return wait_reticle(capture,reselect=reselect,skill=skill,cooldown_reader=self.cooldown)

    def present(self, image, cell):
        from deployment import gunner_present
        return gunner_present(image, cell)

    def cooldown(self,image,skill,read_turns=False):
        from combat import cooldown
        return cooldown(image,skill,read_turns=read_turns)

    def targets(self, enemies, skill):
        import target_priority
        if target_priority.enabled(enemies):
            ranked=sorted(enemies,key=lambda e:(-target_priority.level(e),e.get('hp_fraction',1.)))
            return list(dict.fromkeys(tuple(e['foot']) for e in ranked))
        if skill == 1:
            return [tuple(enemies[0]['foot'])] if enemies else []
        columns = {}
        for enemy in enemies:
            x, y = enemy['foot']
            dx, dy = (x-544)/110, (y-196)/55
            column = enemy.get('column', round((dx+dy)/2)+1)
            row = enemy.get('row', round((dx-dy)/2)+1)
            columns.setdefault(column, []).append((row, enemy))
        health = {c: sum(max(0, e.get('hp_fraction', 1)) for _, e in units)
                  for c, units in columns.items()}
        order = sorted(columns, key=lambda c: (-health[c],
                       -.2*(health.get(c-1, 0)+health.get(c+1, 0)), c))
        return [tuple(min(columns[c], key=lambda item: item[0])[1]['foot']) for c in order]

    def hits(self, image, enemies, skill):
        from combat import area_hits, outline_hits,reticle_center
        if skill not in self.drag_skills: return outline_hits(image,enemies)
        hits=area_hits(image,enemies)
        covered={(e['row'],e['column']) for e in hits}
        # A cannon's sandbag base and HP bar can hide every sampled ground rim.
        # Require both a centered ring and a large actual yellow unit outline.
        for enemy in enemies:
            if enemy.get('sprite')!='antiair' or (enemy['row'],enemy['column']) in covered: continue
            try: cx,cy=reticle_center(image)
            except RuntimeError: continue
            x,y=enemy['foot']
            if abs(cx-x)>20 or abs(cy-y)>15: continue
            colors=image.convert('RGB').crop((x-90,y-150,x+90,y+20)).getdata()
            yellow=sum(r>210 and g>190 and b<90 for r,g,b in colors)
            if yellow>500:
                hits.append({**enemy,'damage_band':'main','occluded_ground':True,
                             'outline_yellow':yellow,'aim_center_verified':True})
        return hits

    def evaluate(self, hits, skill):
        main = [h for h in hits if skill == 1 or h['damage_band'] == 'main']
        score = len(main)+.2*(len(hits)-len(main))+sum(.1*(1-h.get('hp_fraction',1.)) for h in main)
        return main, score

    def confirmation_target(self, hits, skill, target):
        import target_priority
        if target_priority.enabled(hits): return tuple(target)
        return tuple(hits[0]['foot']) if skill == 1 and hits else tuple(target)
