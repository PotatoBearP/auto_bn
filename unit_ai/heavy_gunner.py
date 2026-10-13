"""Heavy gunner policy. Screen observation/input stay in the combat engine."""
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

    def locate_aim(self,capture,reselect=None):
        from combat import wait_reticle
        return wait_reticle(capture,reselect=reselect)

    def present(self, image, cell):
        from deployment import gunner_present
        return gunner_present(image, cell)

    def cooldown(self,image,skill,read_turns=False):
        from combat import cooldown
        return cooldown(image,skill,read_turns=read_turns)

    def targets(self, enemies, skill):
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
        from combat import area_hits, outline_hits
        return area_hits(image, enemies) if skill in self.drag_skills else outline_hits(image, enemies)

    def evaluate(self, hits, skill):
        main = [h for h in hits if skill == 1 or h['damage_band'] == 'main']
        score = len(main)+.2*(len(hits)-len(main))+sum(.1*(1-h['hp_fraction']) for h in main)
        return main, score

    def confirmation_target(self, hits, skill, target):
        return tuple(hits[0]['foot']) if skill == 1 and hits else tuple(target)
