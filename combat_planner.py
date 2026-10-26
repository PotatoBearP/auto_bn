"""Rank modeled actions without screenshots, mouse input, or cooldown guesses."""
import target_priority
import math
from battle_rules import position,validate_models,enemy_cell


def health_fraction(value):
    """Unknown HP receives no wounded-unit priority."""
    if not isinstance(value,(int,float)) or not math.isfinite(value): return 1.
    return max(0.,min(1.,value))


def plan(controllers,enemies,skills_for,force_skill=None,ally_health=None,excluded_anchors=None):
    active=target_priority.enabled(enemies)
    options=[]
    for player,ai in controllers.items():
        validate_models(ai)
        for skill in skills_for[player]:
            if force_skill is not None and skill!=force_skill: continue
            model=ai.skill_models[skill]
            seen=set()
            anchors=model.legal_anchors(enemies)
            # A direct global attack still needs a clickable front unit.
            # Rear units may be shielded even though the attack hits them.
            if model.aiming=='direct' and model.absolute:
                anchors=sorted(anchors)
            for anchor in anchors:
                if (ai.id,skill,tuple(anchor)) in (excluded_anchors or set()): continue
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
    for option in options:
        option['selection_key']=option['priority_key']
        if any(getattr(ai,'skill_priority',None) for ai in controllers.values()):
            preference=getattr(controllers[tuple(option['unit'])],'skill_priority',{}).get(option['skill'],0)
            option['selection_key']=(preference,)+option['selection_key']
        if target_priority.ATTRITION.get() and option['unit_id']=='coward':
            hp=(ally_health or {}).get(tuple(option['unit']))
            option['unit_hp_fraction']=hp
            option['selection_key']=(-health_fraction(hp),)+option['priority_key']
    return sorted(options,key=lambda option:option['selection_key'],reverse=True)
