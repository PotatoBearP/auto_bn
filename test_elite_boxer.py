"""Observed boxer UI and pure-model regressions."""
import unittest
from PIL import Image
import combat
import formation
from battle_rules import CELLS,position
from combat_planner import plan
from paths import TEMPLATES
from unit_ai import choices,get


class EliteBoxerTests(unittest.TestCase):
    def fixture(self,name):
        frame=Image.new('RGB',(1366,768))
        with Image.open(TEMPLATES/(name+'-fixture.png')) as crop:
            frame.paste(crop,(430,80))
        return frame

    def test_registered_and_allowed_in_front_row_formation(self):
        self.assertEqual(choices()['elite_boxer'],'顶尖拳击手')
        self.assertEqual(formation.validate({'version':1,'units':[
            {'row':1,'column':3,'unit':'elite_boxer'}]})['units'][0]['unit'],'elite_boxer')
        with self.assertRaises(ValueError):
            formation.validate({'version':1,'units':[{'row':2,'column':3,'unit':'elite_boxer'}]})

    def test_model_matches_live_ground_overlays(self):
        ai=get('elite_boxer')
        board=[{'row':r,'column':c,'foot':position((r,c))} for r,c in CELLS]
        for name,skill,anchor in [('boxer-start',1,(1,3)),('boxer-skill2',2,(2,3)),
                                  ('boxer-skill3',3,(2,3)),('boxer-skill3-alternate',3,(1,1)),
                                  ('boxer-skill3-middle',3,(1,3))]:
            with self.subTest(name=name):
                observed={(e['row'],e['column']) for e in combat.area_hits(self.fixture(name),board)
                          if e['damage_band']=='main'}
                modeled=ai.skill_models[skill].coverage(anchor)[0]
                # The rock covers this ground cell in the live scene.
                self.assertEqual(observed-{(2,4)},modeled-{(2,4)})

    def test_cross_centers_cover_both_patterns_and_corner_is_clipped(self):
        model=get('elite_boxer').skill_models[3]
        odd=model.coverage((2,3))[0];even=model.coverage((1,3))[0]
        self.assertEqual(odd|even,set(CELLS))
        self.assertFalse(odd&even)
        self.assertEqual(model.coverage((1,1))[0],{(1,1),(1,3),(2,2)})
        self.assertEqual(set(model.legal_anchors([])),set(CELLS))

    def test_reticle_occluded_last_tank_is_still_recognized(self):
        enemies=combat.initial_enemies(self.fixture('boxer-stall-reticle'))
        self.assertEqual([(e['sprite'],e['row'],e['column']) for e in enemies],[('tank',1,3)])

    def test_unreachable_center_uses_equivalent_front_anchor(self):
        ai=get('elite_boxer');player=(599,390)
        enemies=[{'row':1,'column':c,'foot':position((1,c)),'hp_fraction':1.} for c in (2,4)]
        options=plan({player:ai},enemies,{player:(3,)},
                     excluded_anchors={('elite_boxer',3,(2,3))})
        self.assertEqual(options[0]['hit_count'],2)
        self.assertEqual(options[0]['anchor'][0],1)

    def test_third_skill_preferred_and_rock_never_counted_as_enemy(self):
        ai=get('elite_boxer');player=(599,390)
        enemies=[{'row':1,'column':c,'foot':position((1,c)),'hp_fraction':1.} for c in range(1,6)]
        enemies.append({'row':2,'column':4,'foot':position((2,4)),'sprite':'rock'})
        options=plan({player:ai},enemies,{player:ai.skill_order})
        self.assertEqual(options[0]['skill'],3)
        self.assertTrue(all(e.get('sprite')!='rock' for o in options for e in o['hits']))
        self.assertEqual(next(o for o in options if o['skill']==2)['hit_count'],1)

    def test_third_cooldown_reads_its_own_slot(self):
        frame=Image.new('RGB',(1366,768))
        with Image.open(TEMPLATES/'regression-cooldown-icons.png') as icons:
            frame.paste(icons.crop((104,0,152,48)),(381,699))
            frame.paste(icons.crop((0,0,48,48)),(485,699))
        self.assertFalse(combat.cooldown(frame,2,False)['blocked'])
        self.assertTrue(combat.cooldown(frame,3,False)['blocked'])

    def test_body_presence_and_selection_with_adjacent_boxers(self):
        frame=self.fixture('boxer-start');ai=get('elite_boxer')
        for point in ((489,335),(599,390),(709,445)):
            self.assertTrue(ai.present(frame,point))
        self.assertTrue(ai.selected_at(frame,(489,335)))
        self.assertFalse(ai.selected_at(frame,(599,390)))
        self.assertFalse(ai.present(frame,(378,280)))

    def test_deployment_selection_overlay_does_not_hide_right_boxer(self):
        frame=self.fixture('boxer-deployment-overlay');ai=get('elite_boxer')
        occupied={(1,2),(1,3),(1,4)}
        for row,column in formation.cells():
            self.assertEqual(ai.present(frame,formation.position(row,column)),(row,column) in occupied)


if __name__=='__main__': unittest.main()
