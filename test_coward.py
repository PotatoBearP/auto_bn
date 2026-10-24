"""Coward geometry, low-HP scoring and cross-skill decision checks."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import combat
import formation
from unit_ai import get
from paths import COMBAT,VALIDATION


def enemy(row,column,hp=1.,source='health_bar'):
    return {'row':row,'column':column,'hp_fraction':hp,'hp_source':source,
            'foot':[544+110*(row+column-2),196+55*(column-row)]}


class CowardTests(unittest.TestCase):
    def setUp(self): self.ai=get('coward')

    def test_unit_switch_waits_for_highlight_and_new_skill_panel(self):
        old=Image.new('RGB',(1366,768),'red')
        highlighted=Image.new('RGB',(1366,768),'blue')
        ready=Image.new('RGB',(1366,768),'green')
        frames=iter((old,old,highlighted,ready))
        with patch.object(combat,'skill_panel_visible',return_value=True), \
             patch.object(self.ai,'selected_at',side_effect=lambda frame,point:frame is not old), \
             patch.object(combat.time,'sleep'):
            frame=combat.wait_selected_unit(lambda:next(frames),self.ai,(599,390))
        self.assertIs(frame,ready)

    def test_switch_animation_does_not_mark_ready_second_unit_unselectable(self):
        points=[formation.position(1,c) for c in (1,3,5)]
        polls={p:0 for p in points}
        def selected(point):
            polls[point]+=1
            return point!=points[1] or polls[point]>=3
        report=self.preview_case([enemy(2,3)],dict.fromkeys(points,self.ai),
                                 blocked={(points[0],1),(points[0],2)},selection=selected)
        self.assertEqual(report['chosen']['unit'],list(points[1]))
        self.assertEqual(report['chosen']['skill'],1)
        self.assertNotEqual(report['allies'][1]['status'],'unselectable')

    def test_unconfirmed_selection_never_reads_old_unit_skills(self):
        image=Image.new('RGB',(1366,768))
        with patch.object(combat,'skill_panel_visible',return_value=True), \
             patch.object(self.ai,'selected_at',return_value=False), \
             patch.object(combat.time,'sleep'), \
             patch.object(self.ai,'cooldown') as reader:
            self.assertIsNone(combat.wait_selected_unit(lambda:image,self.ai,(599,390),attempts=3))
        reader.assert_not_called()

    def test_vertical_and_horizontal_three_cells(self):
        self.assertEqual(self.ai.covered_cells(3,1),{(1,3),(2,3),(3,3)})
        self.assertEqual(self.ai.covered_cells(3,2),{(1,2),(1,3),(1,4)})
        self.assertEqual(self.ai.covered_cells(1,1),{(1,1),(2,1)})
        self.assertEqual(self.ai.covered_cells(5,2),{(1,4),(1,5)})

    def test_only_front_row_placement_and_front_row_aim(self):
        with self.assertRaisesRegex(ValueError,'第一排'):
            formation.validate({'version':1,'units':[{'row':2,'column':2,'unit':'coward'}]})
        targets=self.ai.targets([enemy(2,3),enemy(1,5)],1)
        self.assertIn((764,306),targets) # Empty front cell can aim at the unit behind it.
        for x,y in targets:
            self.assertAlmostEqual((x-544)/110,(y-196)/55)
            self.assertTrue(544<=x<=984)

    def test_coverage_and_low_health_both_matter(self):
        score=lambda hits:self.ai.evaluate(hits,1)[1]
        self.assertGreater(score([enemy(1,1),enemy(1,2)]),score([enemy(1,1)]))
        self.assertGreater(score([enemy(1,1,.1)]),score([enemy(1,1,1.)]))
        self.assertGreater(score([enemy(1,1,.1)]),score([enemy(1,1),enemy(1,2)]))
        self.assertGreater(score([enemy(1,1),enemy(1,2),enemy(1,3)]),score([enemy(1,1,.1)]))
        self.assertEqual(score([enemy(1,1,.1,'unknown')]),1.)

    def test_skill1_aim_checks_skill1_cooldown(self):
        image=Image.new('RGB',(1366,768))
        with patch.object(combat,'skill_panel_visible',return_value=True), \
             patch.object(combat,'reticle_center',return_value=(764,306)), \
             patch.object(self.ai,'cooldown',return_value={'blocked':False}) as reader:
            self.assertEqual(self.ai.locate_aim(lambda:image,skill=1),(764,306))
            reader.assert_called_once_with(image,1,read_turns=False)

    def test_preview_fixtures_detect_both_skills_and_all_three_units(self):
        with Image.open(VALIDATION/'coward-skill1.png') as image:
            self.assertEqual([self.ai.present(image,formation.position(1,c)) for c in range(1,6)],
                             [False,True,True,True,False])
            self.assertEqual([self.ai.selected_at(image,formation.position(1,c)) for c in range(1,6)],
                             [False,True,False,False,False])
            hits=self.ai.hits(image,[enemy(1,3),enemy(1,4),enemy(2,3)],1)
            self.assertEqual([(e['row'],e['column']) for e in hits],[(1,3),(2,3)])
        with Image.open(VALIDATION/'coward-skill2.png') as image:
            hits=self.ai.hits(image,[enemy(1,3),enemy(1,4),enemy(2,3)],2)
            self.assertEqual([(e['row'],e['column']) for e in hits],[(1,3),(1,4)])

    def preview_case(self,enemies,controllers=None,living=None,selection=None,preview_only=True,blocked=None,mismatch=False,health=None):
        controllers=controllers or {((489,335)):self.ai}
        living=set(controllers) if living is None else set(living)
        image=Image.new('RGB',(1366,768));aim=[544,196];selected=[1]
        selected_player=[next(iter(controllers))]
        self.input_clicks=[]
        self.input_drags=[]
        self.preview_checks=0
        def click(x,y):
            self.input_clicks.append((x,y))
            if (x,y) in controllers: selected_player[0]=(x,y)
            for skill,point in self.ai.skill_points.items():
                if (x,y)==point: selected[0]=skill;aim[:]=[544,196]
        def hits(frame,units,skill):
            self.preview_checks+=1
            column=round((aim[0]-544)/110)+1
            return [] if mismatch else self.ai.predicted_hits(units,column,skill)
        def drag(origin,target,check):
            self.input_drags.append((origin,target));aim[:]=target
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(combat,'ROOT',Path(directory)))
            stack.enter_context(patch.object(formation,'units',return_value=list(controllers.items())))
            stack.enter_context(patch.object(combat.control,'check'))
            stack.enter_context(patch.object(combat.app,'find_game',return_value=1))
            stack.enter_context(patch.object(combat.app,'focus_game'))
            stack.enter_context(patch.object(combat.app,'bounds',return_value=(0,0,1366,768)))
            stack.enter_context(patch.object(combat.app.user32,'IsIconic',return_value=False))
            stack.enter_context(patch.object(combat.app.user32,'GetForegroundWindow',return_value=1))
            stack.enter_context(patch.object(combat.ImageGrab,'grab',return_value=image))
            stack.enter_context(patch.object(combat,'wait_our_turn',return_value=(image,{'our_turn':True})))
            stack.enter_context(patch.object(combat,'skill_panel_visible',return_value=True))
            stack.enter_context(patch.object(combat,'settlement_phase',return_value=None))
            stack.enter_context(patch.object(combat,'observe_enemies',return_value=enemies))
            stack.enter_context(patch.object(combat,'health_bars',return_value=[
                {'foot':list(point),'side':'friendly','hp_fraction':hp}
                for point,hp in (health or {}).items() if hp is not None and point in living]))
            stack.enter_context(patch.object(self.ai,'present',side_effect=lambda frame,point:point in living))
            stack.enter_context(patch.object(self.ai,'selected_at',side_effect=lambda frame,point:
                selection(point) if selection else point in living and point==selected_player[0]))
            stack.enter_context(patch('battle_model.update'))
            stack.enter_context(patch.object(combat.time,'sleep'))
            stack.enter_context(patch.object(self.ai,'cooldown',side_effect=lambda frame,skill,**kw:
                {'blocked':bool(blocked and (selected_player[0],skill) in blocked)}))
            stack.enter_context(patch.object(self.ai,'locate_aim',side_effect=lambda *a,**kw:tuple(aim)))
            stack.enter_context(patch.object(self.ai,'hits',side_effect=hits))
            stack.enter_context(patch.object(combat.mouse,'click',side_effect=click))
            stack.enter_context(patch.object(combat.mouse,'drag',side_effect=drag))
            report=combat.combat_step(preview_only=preview_only)
        return report

    def test_compares_both_skills_instead_of_firing_first_viable_option(self):
        report=self.preview_case([enemy(1,3),enemy(1,4,.2),enemy(1,5,.2),enemy(2,3),enemy(3,3)])
        self.assertEqual(report['chosen']['skill'],2)
        self.assertEqual(report['chosen']['target'],[874,361])
        self.assertEqual(len(report['options']),1)
        self.assertEqual({option['skill'] for option in report['planned_options']},{1,2})
        self.assertEqual(self.preview_checks,0)
        self.assertEqual(len(self.input_drags),0)
        self.assertEqual(report['planning_mode'],'model_first')
        self.assertFalse(report['released'])

    def test_one_high_threat_outranks_three_lower_threats_across_skills(self):
        high={**enemy(2,2),'sprite':'veteran'}
        report=self.preview_case([high,enemy(1,3),enemy(1,4,.1),enemy(1,5,.1)])
        self.assertEqual(report['chosen']['skill'],1)
        self.assertEqual(report['chosen']['target'],[654,251])
        self.assertEqual([(h['row'],h['column']) for h in report['chosen']['hits']],[(2,2)])
        self.assertEqual(report['strategy'],'threat_then_existing_strategy')

    def test_best_skill_on_another_unit_is_used_without_previewing_blocked_candidates(self):
        points=[formation.position(1,c) for c in (1,3,5)]
        report=self.preview_case([enemy(1,3),enemy(1,4),enemy(1,5)],dict.fromkeys(points,self.ai),
                                 blocked={(points[0],2)})
        self.assertEqual(report['chosen']['skill'],2)
        self.assertEqual(report['chosen']['unit'],list(points[1]))
        self.assertEqual(self.preview_checks,0)
        self.assertEqual(len(self.input_drags),0)

    def test_model_decisions_do_not_use_the_gui_range_reader(self):
        point=formation.position(1,1)
        report=self.preview_case([enemy(1,3)],{point:self.ai},mismatch=True)
        self.assertEqual(report['chosen']['hit_count'],1)
        self.assertEqual(self.preview_checks,0)
        self.assertTrue(all(click in (point,*self.ai.skill_points.values()) for click in self.input_clicks))

    def test_dead_middle_coward_is_not_clicked_or_scored(self):
        points=[formation.position(1,c) for c in (1,3,5)]
        report=self.preview_case([enemy(1,3)],dict.fromkeys(points,self.ai),living=[points[0],points[2]])
        self.assertNotIn(points[1],self.input_clicks)
        self.assertNotIn(list(points[1]),[option['unit'] for option in report['options']])
        self.assertEqual(report['allies'][1]['status'],'unseen')

    def test_failed_unit_selection_does_not_send_skills_to_old_selected_unit(self):
        points=[formation.position(1,c) for c in (1,3,5)]
        report=self.preview_case([enemy(1,3)],dict.fromkeys(points,self.ai),
                                 selection=lambda point:point!=points[0])
        self.assertNotEqual(report['chosen']['unit'],list(points[0]))
        self.assertEqual(self.input_clicks[:2],[points[0],points[1]])
        self.assertEqual(report['allies'][0]['status'],'unselectable')

    def test_unit_lost_before_release_retries_without_confirmation_click(self):
        point=formation.position(1,1);checks=[0]
        def selection(position):
            checks[0]+=1
            return checks[0]<4
        with self.assertRaises(combat.CombatRetry):
            self.preview_case([enemy(1,3)],{point:self.ai},selection=selection,preview_only=False)
        self.assertTrue(all(click in (point,*self.ai.skill_points.values()) for click in self.input_clicks))

    def test_next_battle_reobserves_all_three_replenished_units(self):
        points=[formation.position(1,c) for c in (1,3,5)]
        controllers=dict.fromkeys(points,self.ai)
        first=self.preview_case([enemy(1,3)],controllers,living=[points[0]])
        second=self.preview_case([enemy(1,3)],controllers,living=points)
        self.assertEqual(sum(a['status']=='observed' for a in first['allies']),1)
        self.assertEqual(sum(a['status']=='observed' for a in second['allies']),3)

    def test_no_observed_survivors_waits_without_clicking_empty_cells(self):
        point=formation.position(1,1)
        with self.assertRaises(combat.CombatRetry):
            self.preview_case([enemy(1,3)],{point:self.ai},living=[])
        self.assertEqual(self.input_clicks,[])

    def test_low_health_bar_confirms_survivor_when_body_is_occluded(self):
        points=[formation.position(1,c) for c in (1,3,5)]
        bar={'foot':list(points[1]),'side':'friendly','hp_fraction':.01}
        with patch.object(combat,'health_bars',return_value=[bar]), \
             patch.object(self.ai,'present',return_value=False), \
             patch.object(self.ai,'selected_at',return_value=False):
            available,observed=combat.observe_allies(Image.new('RGB',(1366,768)),dict.fromkeys(points,self.ai))
        self.assertEqual(list(available),[points[1]])
        self.assertEqual(observed[1]['hp_fraction'],.01)


if __name__=='__main__': unittest.main()
