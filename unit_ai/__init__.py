"""Registered unit controllers shared by deployment and combat."""
from .heavy_gunner import HeavyGunnerAI
from .coward import CowardAI
from .elite_boxer import EliteBoxerAI
from battle_rules import validate_models

REGISTRY = {'heavy_gunner': HeavyGunnerAI(),'coward':CowardAI(),'elite_boxer':EliteBoxerAI()}
for controller in REGISTRY.values(): validate_models(controller)

def get(unit_id):
    try:
        controller=REGISTRY[unit_id]
        validate_models(controller)
        return controller
    except KeyError:
        raise ValueError(f'未注册单位 AI：{unit_id}') from None

def choices():
    return {unit_id: ai.name for unit_id, ai in REGISTRY.items()}
