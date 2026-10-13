"""Workflow regression checks; no desktop input is sent."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
import automation
import combat
import control
import mouse_backend
import settlement
import deployment
from paths import COMBAT,VALIDATION

class WorkflowTests(unittest.TestCase):
    def test_attack_confirmed_when_next_turn_selects_other_ready_gunner(self):
        image=Image.new('RGB',(1366,768))
        turn={'our_turn':True,'opponent_ui_disappearance_seen':True,'health_change_seen':True}
        with patch.object(combat,'cooldown',return_value={'blocked':False}) as cooldown:
            self.assertEqual(combat.release_evidence(image,1,turn),'turn_transition_and_health_change')
        cooldown.assert_not_called()

    def test_ready_icon_without_turn_or_damage_does_not_confirm_attack(self):
        image=Image.new('RGB',(1366,768))
        with patch.object(combat,'cooldown',return_value={'blocked':False}):
            self.assertIsNone(combat.release_evidence(image,1,{'our_turn':True}))

    def test_reticle_cooldown_rebuilds_decision_without_waiting_for_ring(self):
        image=Image.new('RGB',(1366,768))
        with patch.object(combat,'skill_panel_visible',return_value=True), \
             patch.object(combat,'cooldown',return_value={'blocked':True}), \
             patch.object(combat,'reticle_center') as detect:
            with self.assertRaises(combat.TurnChanged): combat.wait_reticle(lambda:image)
        detect.assert_not_called()

    def test_reticle_reselects_missing_overlay_before_giving_up(self):
        image=Image.new('RGB',(1366,768));clock=[0.0];retries=[]
        def detect(frame):
            if not retries: raise RuntimeError('missing')
            return (765,195)
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory, \
             patch.object(combat,'ROOT',Path(directory)), \
             patch.object(combat,'skill_panel_visible',return_value=True), \
             patch.object(combat,'cooldown',return_value={'blocked':False}), \
             patch.object(combat,'reticle_center',side_effect=detect), \
             patch.object(combat.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(combat.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)):
            point=combat.wait_reticle(lambda:image,timeout=.4,reselect=lambda:retries.append(True))
        self.assertEqual(point,(765,195))
        self.assertEqual(len(retries),1)

    def test_persistent_aim_failure_recovers_instead_of_stopping_combat(self):
        recovered={'skipped':True,'skip_confirmed':True,'settled':True}
        def step(preview,skill,context):
            context['recover_aim_turn']=lambda:recovered
            raise combat.AimUnavailable('missing')
        with patch.object(combat,'_combat_step',side_effect=step):
            self.assertEqual(combat.combat_step(),recovered)

    def test_visible_enemy_without_history_is_not_discarded(self):
        import json
        with Image.open(VALIDATION/'enemy-visible-untracked.png') as source:
            image=source.convert('RGB')
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(combat,'ROOT',Path(directory)):
            (Path(directory)/'battle-state.json').write_text(json.dumps(
                {'initial':False,'last_enemies':[],'initial_roster':[]}),encoding='utf-8')
            enemies=combat.observe_enemies(image)
        self.assertEqual(len(enemies),1)
        self.assertEqual((enemies[0]['row'],enemies[0]['column']),(1,4))
        self.assertEqual(enemies[0]['hp_source'],'full_without_bar')
        self.assertEqual(enemies[0]['hp_fraction'],1.0)

    def test_missing_bar_means_full_even_with_old_damage_record(self):
        import json
        with Image.open(VALIDATION/'enemy-visible-untracked.png') as source:
            image=source.convert('RGB')
        prior={'foot':[988,306],'row':2,'column':4,'hp_fraction':.25}
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(combat,'ROOT',Path(directory)):
            (Path(directory)/'battle-state.json').write_text(json.dumps(
                {'initial':False,'last_enemies':[prior]}),encoding='utf-8')
            enemies=combat.observe_enemies(image)
        self.assertEqual(enemies[0]['hp_fraction'],1.0)
        self.assertEqual(enemies[0]['hp_source'],'full_without_bar')

    def test_highlighted_advanced_enemies_are_full_without_bars(self):
        import json
        with Image.open(VALIDATION/'enemy-outline-progression.png') as source:
            image=source.convert('RGB')
        tracked=[{'foot':[874,141],'row':3,'column':2,'sprite':'tank','hp_fraction':.35},
                 {'foot':[984,196],'row':3,'column':3,'sprite':'tank','hp_fraction':.7}]
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,patch.object(combat,'ROOT',Path(directory)):
            (Path(directory)/'battle-state.json').write_text(json.dumps(
                {'initial':False,'last_enemies':tracked,'initial_roster':tracked}),encoding='utf-8')
            enemies=combat.observe_enemies(image)
        self.assertEqual([(e['row'],e['column']) for e in enemies],[(2,2),(2,3)])
        self.assertEqual([e['hp_fraction'] for e in enemies],[1.0,1.0])
        self.assertTrue(all(e['hp_source']=='full_without_bar' for e in enemies))

    def test_relaxed_sprite_matching_does_not_invent_untracked_enemies(self):
        with Image.open(VALIDATION/'enemy-outline-progression.png') as source:
            image=source.convert('RGB')
        enemies=combat.initial_enemies(image,tracked=[])
        self.assertTrue(all((e['row'],e['column']) in ((2,2),(2,3)) for e in enemies))

    def test_experience_confirm_moves_with_taller_panel(self):
        image=Image.new('RGB',(1366,768),(110,110,110))
        image.paste(settlement.reference_image('experience-title'),(620,172))
        image.paste(settlement.reference_image('experience-confirm'),(726,534))
        stage,button=settlement.dialog(image)
        self.assertEqual(stage,'experience')
        self.assertEqual(button,(726,534,946,576))

    def test_settlement_retries_unaccepted_clicks_then_confirms_transition(self):
        clock=[0.0];stage=['loot'];clicks={'loot':0,'experience':0}
        image=Image.new('RGB',(1366,768))
        def dialog(frame):
            return (stage[0],settlement.REGIONS[stage[0]+'-confirm']) if stage[0]!='map' else (None,None)
        def click(x,y):
            current=stage[0];clicks[current]+=1
            if clicks[current]==2: stage[0]='experience' if current=='loot' else 'map'
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(settlement,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(control,'check'))
            stack.enter_context(patch.object(settlement.app,'find_game',return_value=1))
            stack.enter_context(patch.object(settlement.app,'bounds',return_value=(0,0,1366,768)))
            stack.enter_context(patch.object(settlement.app,'focus_game'))
            stack.enter_context(patch.object(settlement.app.user32,'IsIconic',return_value=False))
            stack.enter_context(patch.object(settlement.app.user32,'GetForegroundWindow',return_value=1))
            stack.enter_context(patch.object(settlement.ImageGrab,'grab',return_value=image))
            stack.enter_context(patch.object(settlement,'dialog',side_effect=dialog))
            stack.enter_context(patch.object(settlement,'matches',side_effect=lambda frame,name:stage[0]=='map'))
            stack.enter_context(patch.object(settlement.mouse,'click',side_effect=click))
            stack.enter_context(patch.object(settlement.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(settlement.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
            result=settlement.finish_battle()
        self.assertEqual(clicks,{'loot':2,'experience':2})
        self.assertEqual(result['confirmed'],['loot','experience'])
        self.assertTrue(result['returned_to_map'])

    def test_aircraft_detection_ignores_selection_background(self):
        with Image.open(deployment.TEMPLATES/'first-aircraft-body.png') as source:
            body=source.convert('RGB')
        for background in ((185,155,105),(80,230,160)):
            image=Image.new('RGB',(1366,768),background)
            image.paste(body,(354,345))
            detected=[cell for cell in deployment.aircraft_cells() if deployment.aircraft_present(image,cell)]
            self.assertEqual(detected,[tuple(deployment.PROFILE['experience_aircraft'])])

    def test_gray_low_health_bar_is_kept_as_a_target(self):
        image=Image.new('RGB',(1366,768),(190,160,100))
        draw=ImageDraw.Draw(image)
        draw.rectangle((615,284,698,301),fill=(0,0,0))
        draw.rectangle((619,288,694,297),fill=(64,64,64))
        enemies=[e for e in combat.health_bars(image) if e['side']=='enemy']
        self.assertEqual(len(enemies),1)
        self.assertEqual(enemies[0]['column'],2)
        self.assertEqual(enemies[0]['hp_fraction'],0)

    def run_case(self,step):
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(automation,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(control,'check'))
            for name,value in [('find_game',1),('bounds',(0,0,1366,768))]:
                stack.enter_context(patch.object(automation.app,name,return_value=value))
            for name,value in [('IsIconic',False),('SetForegroundWindow',True),('GetForegroundWindow',1)]:
                stack.enter_context(patch.object(automation.app.user32,name,return_value=value))
            stack.enter_context(patch.object(automation.time,'sleep'))
            stack.enter_context(patch.object(automation.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768),(0,200,0))))
            stack.enter_context(patch.object(automation.settlement,'phase',side_effect=['map',None,'loot']))
            entered=stack.enter_context(patch.object(automation.app,'encounter',return_value={'clicked':True}))
            deployed=stack.enter_context(patch.object(automation.deployment,'deploy_and_start',return_value={}))
            action=stack.enter_context(patch.object(automation.combat,'combat_step',return_value=step))
            finished=stack.enter_context(patch.object(automation.settlement,'finish_battle',return_value={'returned_to_map':True}))
            try:
                result=automation.run_battle()
                return result,entered.call_count,deployed.call_count,action.call_count,finished.call_count
            except RuntimeError:
                return None,entered.call_count,deployed.call_count,action.call_count,finished.call_count

    def test_victory_enters_settlement_without_waiting_for_another_turn(self):
        step={'released':True,'battle_ended':True,'settled':False,'release_confirmed':True,
              'chosen':{'skill':2,'unit':[489,335],'target':[877,251],'hit_count':2}}
        result,*calls=self.run_case(step)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(calls,[1,1,1,1])

    def test_unconfirmed_release_stops_without_more_attacks_or_settlement(self):
        step={'released':True,'settled':True,'release_confirmed':False,
              'chosen':{'skill':2,'unit':[489,335],'target':[877,251],'hit_count':2}}
        result,*calls=self.run_case(step)
        self.assertIsNone(result)
        self.assertEqual(calls,[1,1,1,0])

    def test_stop_prevents_mouse_press(self):
        control.stop()
        try:
            with patch.object(mouse_backend.win32api,'mouse_event') as event:
                with self.assertRaises(RuntimeError): mouse_backend.down()
                event.assert_not_called()
        finally: control.reset()

    def test_settlement_is_detected_before_our_turn_ui(self):
        image=Image.open(COMBAT/'settlement-loot.png').convert('RGB')
        frame,turn=combat.wait_our_turn(lambda:image,require_transition=True,timeout=1)
        self.assertTrue(turn['battle_ended'])
        self.assertFalse(turn['our_turn'])

    def test_fast_enemy_turn_can_be_confirmed_by_settled_health_change(self):
        import itertools
        image=Image.open(COMBAT/'settlement-loot.png').convert('RGB')
        bars=[{'left':700,'top':300,'hp_fraction':.4}]
        ticks=itertools.count(0,.2)
        with patch.object(combat,'settlement_phase',return_value=None), \
             patch.object(combat,'skill_panel_visible',return_value=True), \
             patch.object(combat,'health_bars',return_value=bars), \
             patch.object(combat.time,'sleep'), \
             patch.object(combat.time,'monotonic',side_effect=lambda:next(ticks)):
            _,turn=combat.wait_our_turn(lambda:image,require_transition=True,
                                       before_signature=((700,300,.8),),timeout=10)
        self.assertTrue(turn['our_turn'])
        self.assertTrue(turn['health_change_seen'])
        self.assertFalse(turn['opponent_ui_disappearance_seen'])

    def test_returning_ui_avoids_health_scans_and_long_waits(self):
        image=Image.new('RGB',(1366,768))
        clock=[0.0]
        def sleep(seconds): clock[0]+=seconds
        with patch.object(combat,'settlement_phase',return_value=None), \
             patch.object(combat,'skill_panel_visible',side_effect=[False]+[True]*20), \
             patch.object(combat,'health_bars') as bars, \
             patch.object(combat.time,'sleep',side_effect=sleep), \
             patch.object(combat.time,'monotonic',side_effect=lambda:clock[0]):
            _,turn=combat.wait_our_turn(lambda:image,require_transition=True,timeout=1)
        self.assertTrue(turn['our_turn'])
        self.assertTrue(turn['opponent_ui_disappearance_seen'])
        self.assertLess(clock[0],.3)
        bars.assert_not_called()

    def test_reticle_waits_for_delayed_animation(self):
        image=Image.new('RGB',(1366,768))
        clock=[0.0]
        def detect(frame):
            if clock[0]<1.8: raise RuntimeError('not ready')
            return (600,300)
        with patch.object(combat,'skill_panel_visible',return_value=True), \
             patch.object(combat,'reticle_center',side_effect=detect), \
             patch.object(combat.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(combat.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)):
            self.assertEqual(combat.wait_reticle(lambda:image),(600,300))
        self.assertGreaterEqual(clock[0],1.8)

    def test_reticle_disappearance_waits_then_rebuilds_decision(self):
        image=Image.new('RGB',(1366,768))
        with patch.object(combat,'skill_panel_visible',return_value=False), \
             patch.object(combat,'wait_our_turn',return_value=(image,{'our_turn':True})) as wait, \
             patch.object(combat,'reticle_center') as detect:
            with self.assertRaises(combat.TurnChanged): combat.wait_reticle(lambda:image)
        wait.assert_called_once()
        detect.assert_not_called()

if __name__=='__main__':
    unittest.main()
