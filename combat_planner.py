"""Rank modeled actions without screenshots, mouse input, or cooldown guesses."""
import target_priority
from battle_rules import position,validate_models,enemy_cell


def plan(controllers,enemies,skills_for,force_skill=None):
    active=target_priority.enabled(enemies)
    options=[]
    for player,ai in controllers.items():
        validate_models(ai)
        for skill in skills_for[player]:
            if force_skill is not None and skill!=force_skill: continue
            model=ai.skill_models[skill]
            seen=set()
            for anchor in model.legal_anchors(enemies):
                hits=model.predict(enemies,anchor)
                if not hits: continue
                signature=tuple(sorted((*enemy_cell(e),e['damage_band']) for e in hits))
                if signature in seen: continue
                seen.add(signature)
                target=position(anchor)
                main,score=ai.evaluate(hits,skill)
                options.append({'unit':list(player),'unit_id':ai.id,'skill':skill,'target':list(target),
                                'anchor':list(anchor),'aiming':model.aiming,
                                'hits':hits,'hit_count':len(hits),'full_hits':len(main),
                                'splash_hits':len(hits)-len(main),'score':round(score,3),
                                'priority_key':target_priority.attack_key(hits,
                                    lambda subset:ai.evaluate(subset,skill)[1],active=active)})
    return sorted(options,key=lambda option:option['priority_key'],reverse=True)
