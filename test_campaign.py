"""Regressions for first-skill priority and repeated encounter clearing."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
import campaign
import combat
import control
from paths import COMBAT,VALIDATION

class CampaignTests(unittest.TestCase):
    def test_entry_scan_skips_mammoth_then_takes_first_other_card(self):
        entries=[{'Text':'Attack!','X':300,'Y':120},{'Text':'Attack!','X':500,'Y':160}]
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(campaign.app,'ENCOUNTER',Path(directory)))
            stack.enter_context(patch.object(campaign.app.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768))))
            stack.enter_context(patch.object(campaign.app,'iter_attack_buttons',return_value=iter(entries)))
            stack.enter_context(patch.object(campaign.app,'mammoth_card',side_effect=[(True,'狂热猛犸象'),(False,'')]))
            result=campaign.app.encounter(allow_empty=True,entry_only=True)
        self.assertEqual(result['target']['X'],500)

    def test_mammoth_avatar_excluded_without_ocr(self):
        image=Image.new('RGB',(1366,768),(150,180,200))
        image.paste(campaign.app.mammoth_avatar(),(178,79))
        with patch.object(campaign.app,'recognize') as ocr:
            excluded,text=campaign.app.mammoth_card(image,{'X':300,'Y':120})
        self.assertTrue(excluded)
        ocr.assert_not_called()

    def test_clipped_attack_entry_needs_no_card_ocr_or_remaining_scan(self):
        def buttons(frame):
            yield {'Text':'Attack!','X':300,'Y':45}
            raise AssertionError('Should stop after the first entry')
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(campaign.app,'ENCOUNTER',Path(directory)))
            stack.enter_context(patch.object(campaign.app.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768))))
            stack.enter_context(patch.object(campaign.app,'iter_attack_buttons',side_effect=buttons))
            ocr=stack.enter_context(patch.object(campaign.app,'recognize'))
            result=campaign.app.encounter(allow_empty=True,first_only=True,entry_only=True)
        self.assertEqual(result['candidates'],1)
        self.assertEqual(result['target']['Y'],45)
        ocr.assert_not_called()

    def test_sweep_targets_front_unit_of_highest_health_column(self):
        enemies=[
            {'foot':[1,1],'row':1,'column':1,'hp_fraction':.8},
            {'foot':[2,2],'row':2,'column':2,'hp_fraction':1},
            {'foot':[3,3],'row':1,'column':2,'hp_fraction':.2},
            {'foot':[4,4],'row':1,'column':3,'hp_fraction':.1}]
        self.assertEqual(combat.sweep_targets(enemies),[(3,3),(1,1),(4,4)])

    def test_sweep_equal_health_prefers_more_splash_health(self):
        enemies=[{'foot':[c,c],'row':1,'column':c,'hp_fraction':hp}
                 for c,hp in [(1,1),(3,1),(4,.5)]]
        self.assertEqual(combat.sweep_targets(enemies)[0],(3,3))

    def test_min_zoom_scan_stops_after_topmost_confirmed_infected(self):
        image=Image.new('RGB',(1366,768),(150,180,200))
        draw=ImageDraw.Draw(image)
        draw.rectangle((960,150,1056,163),fill=(180,120,20))
        draw.rectangle((324,190,420,203),fill=(180,120,20))
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(campaign.app,'OCR',Path(directory)))
            stack.enter_context(patch.object(campaign.app,'ENCOUNTER',Path(directory)))
            ocr=stack.enter_context(patch.object(campaign.app,'recognize',side_effect=[
                [],[{'Text':'Attack!'}],[{'Text':'感染者'}]]))
            found=campaign.app.infected_candidates(image,campaign.app.iter_attack_buttons(image),first_only=True)
            self.assertEqual(len(found),1)
            self.assertEqual((found[0]['X'],found[0]['Y']),(1008,157))
            self.assertEqual(ocr.call_count,3)

    def adapters(self,stack):
        stack.enter_context(patch.object(control,'check'))
        for name,value in [('find_game',1),('bounds',(0,0,1366,768))]:
            stack.enter_context(patch.object(campaign.app,name,return_value=value))
        for name,value in [('IsIconic',False),('SetForegroundWindow',True),('GetForegroundWindow',1)]:
            stack.enter_context(patch.object(campaign.app.user32,name,return_value=value))
        stack.enter_context(patch.object(campaign.time,'sleep'))

    def test_first_skill_skips_second_skill_preview(self):
        image=Image.open(VALIDATION/'skill-1-preview.png').convert('RGB')
        enemies=[b for b in combat.health_bars(image) if b['side']=='enemy']
        self.assertTrue(enemies)
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(combat,'ROOT',Path(directory)))
            stack.enter_context(patch.object(combat.ImageGrab,'grab',return_value=image))
            stack.enter_context(patch.object(combat,'wait_our_turn',return_value=(image,{'our_turn':True})))
            stack.enter_context(patch.object(combat.app,'recognize',return_value=[{'Text':'放弃'}]))
            stack.enter_context(patch.object(combat,'observe_enemies',return_value=enemies))
            stack.enter_context(patch.object(combat,'cooldown',return_value={'blocked':False,'turns':None}))
            click=stack.enter_context(patch.object(combat.mouse,'click'))
            reticle=stack.enter_context(patch.object(combat,'reticle_center'))
            result=combat.combat_step(preview_only=True)
            self.assertEqual(result['chosen']['skill'],1)
            self.assertEqual(len(result['options']),1)
            reticle.assert_not_called()
            self.assertNotIn(combat.SKILLS[2],[tuple(c.args) for c in click.call_args_list])

    def test_second_skill_stops_at_first_effective_target(self):
        image=Image.new('RGB',(1366,768))
        enemies=[{'foot':[544,196],'hp_fraction':1}, {'foot':[654,251],'hp_fraction':1}]
        hit={**enemies[0],'damage_band':'main'}
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(combat,'ROOT',Path(directory)))
            stack.enter_context(patch.object(combat.ImageGrab,'grab',return_value=image))
            stack.enter_context(patch.object(combat,'settlement_phase',return_value=None))
            stack.enter_context(patch.object(combat,'skill_panel_visible',return_value=True))
            stack.enter_context(patch.object(combat,'wait_our_turn',return_value=(image,{'our_turn':True})))
            stack.enter_context(patch.object(combat.app,'recognize',return_value=[{'Text':'放弃'}]))
            stack.enter_context(patch.object(combat,'observe_enemies',return_value=enemies))
            stack.enter_context(patch.object(combat,'cooldown',side_effect=lambda frame,skill,**kw:{'blocked':skill==1}))
            stack.enter_context(patch.object(combat,'reticle_center',return_value=(544,196)))
            hits=stack.enter_context(patch.object(combat,'skill_hits',return_value=[hit]))
            click=stack.enter_context(patch.object(combat.mouse,'click'))
            result=combat.combat_step(preview_only=True)
            self.assertEqual(result['chosen']['skill'],2)
            self.assertEqual(result['chosen']['unit'],list(combat.PLAYERS[0]))
            self.assertEqual(len(result['options']),1)
            hits.assert_called_once()
            # Second gunner is selected once for skill 1, never again for skill 2.
            self.assertEqual([c.args for c in click.call_args_list].count(combat.PLAYERS[1]),1)

    def test_all_four_cooldowns_pass_once_then_wait_for_ui(self):
        image=Image.open(VALIDATION/'skill-1-preview.png').convert('RGB')
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(combat,'ROOT',Path(directory)))
            stack.enter_context(patch.object(combat.ImageGrab,'grab',return_value=image))
            stack.enter_context(patch.object(combat,'settlement_phase',return_value=None))
            stack.enter_context(patch.object(combat,'skill_panel_visible',return_value=True))
            wait=stack.enter_context(patch.object(combat,'wait_our_turn',side_effect=[
                (image,{'our_turn':True}),
                (image,{'our_turn':True,'opponent_ui_disappearance_seen':True})]))
            stack.enter_context(patch.object(combat.app,'recognize',return_value=[{'Text':'放弃'}]))
            stack.enter_context(patch.object(combat,'observe_enemies',return_value=[{'foot':[544,196]}]))
            cooldown=stack.enter_context(patch.object(combat,'cooldown',return_value={'blocked':True}))
            click=stack.enter_context(patch.object(combat.mouse,'click'))
            result=combat.combat_step()
            self.assertTrue(result['skipped'])
            self.assertTrue(result['skip_confirmed'])
            self.assertEqual(cooldown.call_count,8)
            self.assertEqual([c.args for c in click.call_args_list].count((70,203)),1)
            self.assertTrue(wait.call_args.kwargs['require_transition'])

    def test_victory_interrupts_targeting_without_mouse_input(self):
        image=Image.open(COMBAT/'settlement-loot.png').convert('RGB')
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(combat,'ROOT',Path(directory)))
            stack.enter_context(patch.object(combat.ImageGrab,'grab',return_value=image))
            click=stack.enter_context(patch.object(combat.mouse,'click'))
            reticle=stack.enter_context(patch.object(combat,'reticle_center'))
            result=combat.combat_step()
            self.assertTrue(result['battle_ended'])
            self.assertFalse(result['released'])
            click.assert_not_called()
            reticle.assert_not_called()

    def test_visible_campaign_keeps_fighting_until_empty(self):
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(campaign,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(campaign.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768))))
            stack.enter_context(patch.object(campaign.settlement,'phase',return_value='map'))
            target={'X':538,'Y':358,'enemy':'感染者'}
            stack.enter_context(patch.object(campaign.app,'encounter',side_effect=[
                {'candidates':1,'target':target},{'candidates':1,'target':target},
                {'candidates':0,'clear':True}]))
            battle=stack.enter_context(patch.object(campaign.automation,'run_battle',return_value={'actions':[{}]}))
            result=campaign.run_campaign(scope='visible')
            self.assertEqual(battle.call_count,2)
            self.assertEqual(result['status'],'complete')
            self.assertEqual(len(result['battles']),2)

    def test_legacy_world_scope_never_drags_map(self):
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(campaign,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(campaign.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768))))
            stack.enter_context(patch.object(campaign.settlement,'phase',return_value='map'))
            stack.enter_context(patch.object(campaign.app,'encounter',return_value={'candidates':0,'clear':True}))
            drag=stack.enter_context(patch.object(combat.mouse,'drag'))
            result=campaign.run_campaign(scope='world')
        self.assertEqual(result['scope'],'visible')
        self.assertEqual(result['scanned_views'],1)
        self.assertEqual(result['status'],'complete')
        drag.assert_not_called()

    def test_uncertain_cards_without_entry_do_not_stop_campaign(self):
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            self.adapters(stack)
            stack.enter_context(patch.object(campaign,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(campaign.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768))))
            stack.enter_context(patch.object(campaign.settlement,'phase',return_value='map'))
            stack.enter_context(patch.object(campaign.app,'encounter',return_value={'candidates':0,'clear':False}))
            result=campaign.run_campaign(scope='visible')
            import json
            result=json.loads((Path(directory)/'campaign-result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'],'complete')
            self.assertTrue(result['no_attack_entry_confirmed'])
            self.assertNotIn('no_infected_confirmed',result)

if __name__=='__main__':
    unittest.main()
