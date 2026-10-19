"""Shared-model contracts: existing units, mixed teams and future controllers."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from battle_rules import SkillModel,validate_models,position
from combat_planner import plan
from unit_ai import get


def enemy(row,column,kind='crew',hp=1.):
    return {'row':row,'column':column,'sprite':kind,'hp_fraction':hp,
            'hp_source':'health_bar','foot':list(position((row,column)))}


class PlannerTests(unittest.TestCase):
    def test_heavy_gunner_models_fixed_sweep_and_forward_column_splash(self):
        models=get('heavy_gunner').skill_models
        main,splash=models[1].coverage((1,1))
        self.assertEqual(main,{(r,c) for r in (1,2) for c in range(1,6)})
        self.assertEqual(splash,set())
        main,splash=models[2].coverage((2,3))
        self.assertEqual(main,{(2,3),(3,3)})
        self.assertEqual(splash,{(2,2),(2,4),(3,2),(3,4)})

    def test_mixed_team_has_one_shared_ranking_without_gui_readers(self):
        gunner=get('heavy_gunner');coward=get('coward')
        controllers={(489,335):gunner,(599,390):coward}
        enemies=[enemy(3,4,'artillery'),enemy(1,5,'veteran'),enemy(1,1,'armoredcar'),enemy(3,2,'antiair')]
        with patch.object(gunner,'hits',side_effect=AssertionError('No GUI range reads')), \
             patch.object(coward,'hits',side_effect=AssertionError('No GUI range reads')):
            options=plan(controllers,enemies,{p:ai.skill_order for p,ai in controllers.items()})
        self.assertEqual({o['unit_id'] for o in options},{'heavy_gunner','coward'})
        self.assertEqual(options[0]['unit_id'],'heavy_gunner')
        self.assertEqual(options[0]['skill'],2)
        self.assertEqual({e['sprite'] for e in options[0]['hits'] if e['sprite'] in ('artillery','veteran')},
                         {'artillery','veteran'})
        self.assertEqual(options[0]['priority_key'],max(o['priority_key'] for o in options))

    def test_future_unit_needs_only_its_declarative_shape_for_planning(self):
        ai=SimpleNamespace(id='future_unit',name='新单位',skill_order=(1,),drag_skills=(1,),
                           skill_models={1:SkillModel('drag','front',main=((0,0),(1,0)))},
                           evaluate=lambda hits,skill:(hits,float(len(hits))))
        ai.hits=Mock(side_effect=AssertionError('Must never be called'))
        options=plan({(378,280):ai},[enemy(1,3),enemy(2,3)],{(378,280):(1,)})
        self.assertEqual(options[0]['anchor'],[1,3])
        self.assertEqual(options[0]['hit_count'],2)
        ai.hits.assert_not_called()

    def test_missing_or_inconsistent_model_is_rejected_without_legacy_fallback(self):
        ai=SimpleNamespace(name='缺模型单位',skill_order=(1,),drag_skills=(1,))
        with self.assertRaisesRegex(ValueError,'SkillModel'): validate_models(ai)
        ai.skill_models={1:SkillModel('direct')}
        with self.assertRaisesRegex(ValueError,'瞄准方式'): validate_models(ai)

    def test_dead_units_are_not_needed_in_planning_and_empty_anchor_is_legal(self):
        ai=get('coward')
        options=plan({(378,280):ai},[enemy(2,3,'veteran')],{(378,280):(1,2)})
        self.assertEqual({tuple(o['unit']) for o in options},{(378,280)})
        self.assertEqual(options[0]['anchor'],[1,3])

    def test_coward_full_three_cell_attacks_cannot_use_edge_centers(self):
        ai=get('coward')
        for model in ai.skill_models.values():
            self.assertEqual(model.legal_anchors([]),((1,2),(1,3),(1,4)))
        options=plan({(378,280):ai},[enemy(1,2)],{(378,280):(1,2)})
        self.assertTrue(all(option['anchor'][1] in (2,3,4) for option in options))

    def test_fixed_sweep_confirmation_point_must_be_inside_its_legal_area(self):
        model=get('heavy_gunner').skill_models[1]
        enemies=[enemy(3,2,'antiair'),enemy(3,4,'artillery'),enemy(1,5,'veteran')]
        self.assertEqual(model.legal_anchors(enemies),((1,5),))


if __name__=='__main__': unittest.main()
