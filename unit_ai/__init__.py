"""Registered unit controllers shared by deployment and combat."""
from .heavy_gunner import HeavyGunnerAI

REGISTRY = {'heavy_gunner': HeavyGunnerAI()}

def get(unit_id):
    try:
        return REGISTRY[unit_id]
    except KeyError:
        raise ValueError(f'未注册单位 AI：{unit_id}') from None

def choices():
    return {unit_id: ai.name for unit_id, ai in REGISTRY.items()}
