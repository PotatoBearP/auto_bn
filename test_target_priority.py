"""Threat tiers and vehicle replacement do not depend on desktop input."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import combat
import target_priority as priority
from unit_ai import get
from paths import COMBAT,VALIDATION


def unit(kind,row=1,column=1,hp=1.):
    return {'sprite':kind,'row':row,'column':column,'hp_fraction':hp,'hp_source':'health_bar'}


class ThreatTests(unittest.TestCase):
    def key(self,hits):
        return priority.attack_key(hits,lambda subset:get('coward').evaluate(subset,1)[1])

    def test_high_before_low_before_none_regardless_of_lower_tier_numbers(self):
        self.assertGreater(self.key([unit('artillery')]),self.key([unit('armoredcar',hp=.01)]*100))
        self.assertGreater(self.key([unit('veteran')]),self.key([unit('antiair')]*1000))
        self.assertGreater(self.key([unit('crew')]),self.key([unit('antiair',hp=.01)]*100))
        self.assertGreater(self.key([unit('unknown')]),self.key([unit('antiair')]))

    def test_same_tier_preserves_coverage_and_low_health_strategy(self):
        self.assertGreater(self.key([unit('veteran',hp=.1)]),self.key([unit('veteran')]))
        self.assertGreater(self.key([unit('veteran')]*3),self.key([unit('veteran',hp=.1)]))
        self.assertGreater(self.key([unit('veteran'),unit('crew')]),self.key([unit('veteran'),unit('antiair')]))

    def test_gunner_can_aim_directly_at_rear_high_threat(self):
        low={**unit('armoredcar'),'foot':[544,196]}
        high={**unit('artillery',3,4),'foot':[1094,251]}
        for skill in (1,2):
            targets=get('heavy_gunner').targets([low,high],skill)
            self.assertEqual(targets[0],(1094,251))
            self.assertIn((544,196),targets)

    def test_gunner_uses_explosive_skill_when_only_antiair_remains(self):
        self.assertEqual(get('heavy_gunner').available_skills([unit('antiair')]),(2,))
        self.assertEqual(get('heavy_gunner').available_skills([unit('antiair'),unit('crew')]),(1,2))

    def test_new_passenger_invalidates_a_pending_no_threat_cleanup_decision(self):
        self.assertTrue(priority.new_threat_before_cleanup([unit('antiair')],[unit('antiair'),unit('crew')]))
        self.assertFalse(priority.new_threat_before_cleanup([unit('antiair')],[unit('antiair')]))

    def test_occluded_antiair_requires_real_outline_and_centered_aim(self):
        gunner=get('heavy_gunner')
        with Image.open(VALIDATION/'antiair-occluded.png') as image:
            target={**unit('antiair',2,2),'foot':[766,195]}
            hits=gunner.hits(image,[target],2)
            self.assertEqual(len(hits),1)
            self.assertTrue(hits[0]['occluded_ground'])
        with Image.open(VALIDATION/'threat-formation.png') as image:
            target={**unit('antiair',3,2),'foot':[874,141]}
            self.assertEqual(gunner.hits(image,[target],1),[])

    def test_second_passenger_appearance_is_not_missed_after_cannon_death(self):
        with Image.open(VALIDATION/'threat-guncrew.png') as image, \
             tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(combat,'ROOT',Path(directory)):
            enemies=combat.observe_enemies(image)
        self.assertEqual(len(enemies),1)
        self.assertEqual(enemies[0]['sprite'],'crew')
        self.assertEqual(enemies[0]['threat_level'],priority.LOW)

    def test_disembarked_infantry_gets_new_identity_and_current_hp(self):
        state={}
        vehicle=priority.annotate([unit('armoredcar',hp=.03)],[],state)[0]
        crew=priority.annotate([unit('crew',hp=.8)],[vehicle],state)[0]
        self.assertNotEqual(crew['entity_id'],vehicle['entity_id'])
        self.assertEqual(crew['replacement_of'],vehicle['entity_id'])
        self.assertTrue(crew['spawned_from_vehicle'])
        self.assertEqual(crew['hp_fraction'],.8)
        self.assertEqual(crew['threat_level'],priority.LOW)
        self.assertEqual(state['enemy_events'][0]['event'],'occupant_observed')
        again=priority.annotate([unit('crew',hp=.7)],[crew],state)[0]
        self.assertEqual(again['entity_id'],crew['entity_id'])
        self.assertEqual(again['hp_fraction'],.7)

    def test_unknown_replacement_does_not_inherit_destroyed_artillery_type_or_hp(self):
        state={}
        vehicle=priority.annotate([unit('artillery',hp=.02)],[],state)[0]
        unknown=unit(None,hp=1.)
        unknown['hp_source']='full_without_bar'
        current=priority.annotate([unknown],[vehicle],state)[0]
        self.assertEqual(current['threat_level'],priority.LOW)
        self.assertIsNone(current['sprite'])
        self.assertNotEqual(current['entity_id'],vehicle['entity_id'])
        self.assertEqual(current['hp_fraction'],1.)
        self.assertTrue(current['priority_mode'])

    def test_passenger_is_new_target_after_a_gap_in_vehicle_death_animation(self):
        state={}
        vehicle=priority.annotate([unit('armoredcar',hp=.02)],[],state)[0]
        priority.annotate([], [vehicle],state)
        crew=priority.annotate([unit('crew',hp=1.)],[],state)[0]
        self.assertTrue(crew['spawned_from_vehicle'])
        self.assertEqual(crew['replacement_of'],vehicle['entity_id'])
        self.assertNotEqual(crew['entity_id'],vehicle['entity_id'])
        self.assertEqual(crew['hp_fraction'],1.)

    def test_current_scene_has_six_units_and_no_road_tiles_as_antiair(self):
        with Image.open(VALIDATION/'threat-formation.png') as image, \
             tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(combat,'ROOT',Path(directory)):
            enemies=combat.observe_enemies(image)
        self.assertEqual(len(enemies),6)
        self.assertEqual(sorted(e['sprite'] for e in enemies),
                         ['antiair','armoredcar','armoredcar','artillery','rocketteam','veteran'])
        self.assertEqual(sum(e['threat_level']==priority.HIGH for e in enemies),2)

    def test_highlighted_veteran_remains_high_threat_after_artillery_is_destroyed(self):
        with Image.open(VALIDATION/'threat-highlighted.png') as image, \
             tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(combat,'ROOT',Path(directory)):
            enemies=combat.observe_enemies(image)
        self.assertEqual(len(enemies),5)
        self.assertEqual([e['sprite'] for e in enemies if e['threat_level']==priority.HIGH],['veteran'])

    def test_disembarked_passenger_is_recognized_as_new_low_threat_in_real_frame(self):
        with Image.open(VALIDATION/'threat-disembarked.png') as image, \
             tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(combat,'ROOT',Path(directory)):
            state={'initial':False}
            prior=priority.annotate([unit('armoredcar',hp=.02)],[],state)
            state['last_enemies']=prior
            (Path(directory)/'battle-state.json').write_text(json.dumps(state))
            enemies=combat.observe_enemies(image)
        crew=next(e for e in enemies if e.get('sprite')=='crew')
        self.assertEqual(len(enemies),3)
        self.assertEqual(crew['threat_level'],priority.LOW)
        self.assertTrue(crew['spawned_from_vehicle'])
        self.assertEqual(crew['hp_fraction'],1.)

    def test_empty_observation_does_not_retain_destroyed_vehicle(self):
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory, \
             patch.object(combat,'ROOT',Path(directory)), \
             patch.object(combat,'health_bars',return_value=[]), \
             patch.object(combat,'initial_enemies',return_value=[]):
            path=Path(directory)/'battle-state.json'
            path.write_text(json.dumps({'initial':False,'last_enemies':[unit('armoredcar')]}))
            self.assertEqual(combat.observe_enemies(Image.new('RGB',(1366,768))),[])
            self.assertEqual(json.loads(path.read_text())['last_enemies'],[])


if __name__=='__main__': unittest.main()
