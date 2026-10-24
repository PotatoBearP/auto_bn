"""Attrition policy isolation, obstacle exclusion and repeat settlement."""
import unittest
from unittest.mock import patch
import attrition
import target_priority as priority
from battle_rules import SkillModel

class AttritionTests(unittest.TestCase):
    def test_coverage_outranks_finishing_and_threat(self):
        token=priority.ATTRITION.set(True)
        try:
            weak=[{'hp_fraction':.2,'hp_source':'health_bar','sprite':'crew'}]
            full=[{'hp_fraction':1.,'hp_source':'health_bar','sprite':'artillery'}]*3
            self.assertGreater(priority.attack_key(full,len),priority.attack_key(weak,len))
            self.assertFalse(priority.enabled(full))
            self.assertEqual(priority.attack_key([{'hp_fraction':.1}],len)[2],0)
        finally: priority.ATTRITION.reset(token)

    def test_obstacles_are_empty_cells_without_blocking_area(self):
        enemies=[{'row':1,'column':2,'kind':'obstacle'},
                 {'row':1,'column':3,'sprite':'crew'}]
        model=SkillModel('drag',main=((0,0),(0,1)))
        hits=model.predict(enemies,(1,2))
        self.assertEqual([e['column'] for e in hits],[3])

    def test_context_is_restored_on_error_and_config_is_three_front_cowards(self):
        with patch.object(attrition.sweep,'run_loop',side_effect=RuntimeError('stop')) as run:
            with self.assertRaises(RuntimeError): attrition.run_loop(max_battles=1)
        self.assertFalse(priority.ATTRITION.get())
        config=run.call_args.kwargs['config']
        self.assertEqual([u['column'] for u in config['units']],[1,3,5])
        self.assertTrue(all(u['row']==1 and u['unit']=='coward' for u in config['units']))

    def test_experience_is_recognized_before_generic_result_panel(self):
        import settlement
        from PIL import Image
        frame=Image.new('RGB',(1366,768))
        token=priority.ATTRITION.set(True)
        try:
            with patch.object(settlement,'locate_region',side_effect=lambda image,name,low,high:
                    (620,232,732,274) if name=='experience-title' else (726,474,946,516)), \
                 patch('pvp.result_dialog') as generic:
                self.assertEqual(settlement.dialog(frame)[0],'experience')
                generic.assert_not_called()
        finally: priority.ATTRITION.reset(token)

    def test_existing_shifted_defeat_fixture_is_recognized(self):
        import settlement
        from PIL import Image
        token=priority.ATTRITION.set(True)
        try:
            with Image.open('artifacts/validation/pvp/defeat-shifted.png') as image:
                stage,button=settlement.dialog(image.convert('RGB'))
            self.assertEqual(stage,'loot')
            self.assertIsNotNone(button)
        finally: priority.ATTRITION.reset(token)

    def test_live_deployment_start_button_is_not_merged_with_health_bar(self):
        import deployment
        from PIL import Image
        with Image.open('assets/fixtures/attrition-deployment.png') as image, \
             patch.object(deployment.app,'recognize',return_value=[{'Text':'开战'}]):
            point,region,text=deployment.locate_start_button(image)
        self.assertTrue(1190<point[0]<1365)
        self.assertTrue(460<point[1]<520)

    def test_live_board_has_eleven_enemies_and_two_obstacles(self):
        import attrition_vision
        from battle_rules import CELLS,position
        from PIL import Image
        with Image.open('assets/fixtures/attrition-deployment.png') as image:
            enemies=attrition_vision.enemies(image)
            obstacles=[cell for cell in CELLS if attrition_vision.obstacle_at(image,position(cell))]
        self.assertEqual(obstacles,[(1,3),(1,4)])
        self.assertEqual(len(enemies),11)
        self.assertFalse(any((e['row'],e['column']) in obstacles for e in enemies))

    def test_all_three_live_cowards_are_recognized_without_adding_units(self):
        import formation
        from unit_ai import get
        from PIL import Image
        ai=get('coward')
        with Image.open('assets/fixtures/attrition-deployment.png') as image:
            seen=[cell for cell in formation.cells() if ai.present(image,formation.position(*cell))]
        self.assertEqual(seen,[(1,1),(1,3),(1,5)])

    def test_live_boss_score_dialog_is_recognized(self):
        import settlement
        from PIL import Image
        token=priority.ATTRITION.set(True)
        try:
            with Image.open('assets/fixtures/attrition-score.png') as image:
                stage,button=settlement.dialog(image)
            self.assertEqual(stage,'loot')
            self.assertEqual(len(button),4)
        finally: priority.ATTRITION.reset(token)

    def test_dialog_stability_ignores_animated_background(self):
        from PIL import Image
        from attrition_settlement import dialog_key
        with Image.open('assets/fixtures/attrition-score.png') as image:
            changed=image.copy();changed.paste('red',(500,100,980,170))
            self.assertEqual(dialog_key(image,'loot',(756,535,890,575)),
                             dialog_key(changed,'loot',(756,535,890,575)))

    def test_no_skills_on_last_survivor_clicks_give_up_even_without_targets(self):
        from test_coward import CowardTests
        import formation
        case=CowardTests();case.setUp()
        points=[formation.position(1,c) for c in (1,3,5)]
        token=priority.ATTRITION.set(True)
        try:
            with patch('pvp.pass_available',return_value=True):
                result=case.preview_case([],dict.fromkeys(points,case.ai),living=[points[-1]],
                    blocked={(points[-1],1),(points[-1],2)},preview_only=False)
            self.assertEqual(result['reason'],'all_survivors_no_skills')
            self.assertTrue(result['skipped'])
            self.assertIn((70,203),case.input_clicks)
            self.assertNotIn(points[0],case.input_clicks)
            self.assertNotIn(points[1],case.input_clicks)
        finally: priority.ATTRITION.reset(token)

    def test_ready_skill_on_another_survivor_prevents_give_up(self):
        from test_coward import CowardTests,enemy
        import formation
        case=CowardTests();case.setUp()
        points=[formation.position(1,c) for c in (1,3,5)]
        token=priority.ATTRITION.set(True)
        try:
            result=case.preview_case([enemy(1,2)],dict.fromkeys(points,case.ai),
                blocked={(points[0],1),(points[0],2)})
            self.assertNotIn((70,203),case.input_clicks)
            self.assertIn('chosen',result)
        finally: priority.ATTRITION.reset(token)

    def test_humanoid_air_units_are_empty_in_live_board_and_skill_models(self):
        import attrition_vision
        from unit_ai import get
        from PIL import Image
        with Image.open('assets/fixtures/attrition-deployment-2.png') as image:
            all_units=attrition_vision.enemies(image,include_air=True)
            targets=attrition_vision.enemies(image)
        self.assertEqual({(e['row'],e['column']) for e in all_units if e['sprite']=='airflyer'},
                         {(1,4),(2,1)})
        self.assertFalse(any(e['sprite']=='airflyer' for e in targets))
        ai=get('coward')
        flying={'row':1,'column':3,'sprite':'airflyer'}
        self.assertEqual(ai.predicted_hits([flying],3,1),[])
        self.assertEqual(ai.skill_models[1].predict([flying],(1,3)),[])
        self.assertEqual(ai.skill_models[2].predict([flying],(1,3)),[])

    def test_loading_art_is_not_next_battle(self):
        from PIL import Image
        from attrition_settlement import ready_phase
        with Image.open('assets/fixtures/attrition-loading.png') as image:
            self.assertIsNone(ready_phase(image))

    def test_first_attack_chooses_three_enemies_instead_of_rubble_column(self):
        from PIL import Image
        import attrition_vision
        from combat_planner import plan
        from unit_ai import get
        with Image.open('assets/fixtures/attrition-missed-column.png') as image:
            enemies=attrition_vision.enemies(image)
        self.assertIn((1,4),{(e['row'],e['column']) for e in enemies})
        self.assertNotIn((1,2),{(e['row'],e['column']) for e in enemies})
        token=priority.ATTRITION.set(True)
        try:
            options=plan({(378,280):get('coward')},enemies,{(378,280):(1,2)})
            self.assertEqual(options[0]['anchor'],[1,4])
            # Both shapes hit three here. The row contains two red brutes,
            # so the newer value tiebreak prefers it over the tank column.
            self.assertEqual(options[0]['skill'],2)
            self.assertEqual(options[0]['hit_count'],3)
            self.assertEqual({(e['row'],e['column']) for e in options[0]['hits']},{(1,3),(1,4),(1,5)})
        finally: priority.ATTRITION.reset(token)

    def test_rubble_is_ignored_even_when_a_health_bar_is_reported_there(self):
        import combat
        import json
        import tempfile
        from pathlib import Path
        from PIL import Image
        bar={'side':'enemy','row':1,'column':2,'foot':[654,251],'hp_fraction':.1}
        token=priority.ATTRITION.set(True)
        try:
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(combat,'ROOT',Path(directory)), \
                 patch.object(combat,'health_bars',return_value=[bar]), \
                 Image.open('assets/fixtures/attrition-missed-column.png') as image:
                enemies=combat.observe_enemies(image)
                state=json.loads((Path(directory)/'battle-state.json').read_text(encoding='utf-8'))
            self.assertFalse(any((e['row'],e['column'])==(1,2) for e in enemies))
            self.assertIn({'row':1,'column':2,'kind':'obstacle'},state['ignored_obstacles'])
        finally: priority.ATTRITION.reset(token)

if __name__=='__main__': unittest.main()
