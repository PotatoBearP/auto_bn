"""Board coordinates, observation provenance, and per-turn persistence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import battle_model
import combat
from paths import COMBAT,VALIDATION


class BattleModelTests(unittest.TestCase):
    def test_third_row_uses_three_local_columns_and_shared_board_coordinates(self):
        model=battle_model.build([{'row':3,'column':2,'hp_fraction':.375,
                                   'hp_source':'health_bar','sprite':'flyer'}])
        self.assertEqual(len(model['cells']),13)
        rear=[c for c in model['cells'] if c['row']==3]
        self.assertEqual([c['column'] for c in rear],[1,2,3])
        self.assertEqual([c['board_column'] for c in rear],[2,3,4])
        self.assertTrue(rear[0]['occupied'])
        self.assertEqual(rear[0]['hp_fraction'],.375)
        self.assertFalse(rear[0]['estimated'])
        self.assertEqual(model['enemy_count'],1)

    def test_empty_unknown_and_estimated_health_remain_distinct(self):
        model=battle_model.build([
            {'row':1,'column':1,'hp_fraction':1.,'hp_source':'full_without_bar'},
            {'row':1,'column':2},
            {'row':1,'column':3,'hp_fraction':.001,'hp_source':'health_bar'}])
        self.assertIn('100%~',battle_model.render(model))
        self.assertTrue(model['cells'][1]['occupied'])
        self.assertIsNone(model['cells'][1]['hp_fraction'])
        self.assertFalse(model['cells'][3]['occupied'])
        self.assertIsNone(model['cells'][3]['hp_fraction'])

    def test_retry_updates_same_turn_and_successful_transition_appends_history(self):
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(battle_model,'COMBAT',Path(directory)):
            self.assertEqual(battle_model.record([])['turn'],1)
            self.assertEqual(battle_model.record([])['turn'],1)
            self.assertEqual(battle_model.record([],advance=True)['turn'],2)
            self.assertEqual(battle_model.record([])['turn'],2)
            history=[json.loads(line) for line in (Path(directory)/'enemy-turns.jsonl').read_text().splitlines()]
            self.assertEqual([m['turn'] for m in history],[1,2])
            battle_model.reset()
            self.assertEqual(battle_model.record([])['turn'],1)

    def test_live_debug_fixture_recognizes_all_nine_units_without_changing_ground_ai(self):
        with Image.open(VALIDATION/'enemy-board-nine.png') as image, \
             tempfile.TemporaryDirectory(dir=COMBAT) as directory, \
             patch.object(combat,'ROOT',Path(directory)), \
             patch.object(battle_model,'COMBAT',Path(directory)):
            ground=combat.observe_enemies(image)
            self.assertEqual(len(ground),7)
            model=battle_model.update(image,ground)
        self.assertEqual(model['enemy_count'],9)
        self.assertEqual([sum(c['occupied'] for c in model['cells'] if c['row']==r)
                          for r in (1,2,3)],[4,3,2])
        self.assertEqual([c['unit'] for c in model['cells'] if c['row']==3 and c['occupied']],
                         ['flyer','flyer'])


if __name__=='__main__': unittest.main()
