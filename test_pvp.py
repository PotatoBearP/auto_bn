"""PVP entry workflow checks without sending desktop input."""
import tempfile
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
from PIL import Image,ImageDraw
import pvp

class PvpTests(unittest.TestCase):
    def test_shifted_defeat_dialog_and_narrow_confirm_are_recognized(self):
        with Image.open(Path('artifacts/validation/pvp/defeat-shifted.png')) as source:
            frame=source.convert('RGB')
        outcome,point=pvp.result_dialog(frame)
        self.assertEqual(outcome,'defeat')
        self.assertLess(abs(point[0]-874),8)
        self.assertLess(abs(point[1]-514),8)
        self.assertEqual(pvp.stage(frame),'defeat')

    def test_orange_button_alone_is_not_treated_as_result_dialog(self):
        frame=Image.new('RGB',(1366,768))
        ImageDraw.Draw(frame).rectangle((807,495,942,535),fill=(240,150,20))
        self.assertEqual(pvp.result_dialog(frame),(None,None))

    def test_failed_defeat_frame_confirms_then_waits_for_map(self):
        with Image.open(Path('artifacts/validation/pvp/defeat-shifted.png')) as source:
            defeated=source.convert('RGB')
        base=Image.new('RGB',(1366,768));base.paste(pvp.reference('entry'),(791,679))
        clock=[0.0];clicks=[]
        def capture(): return base if clicks else defeated
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(pvp.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
            result=pvp.finish_defeat(capture,clicks.append)
        self.assertEqual(result['returned'],'map')
        self.assertEqual(len(clicks),1)

    def test_ranked_dialog_accepts_small_control_shift(self):
        image=Image.new('RGB',(1366,768),(60,60,60))
        for name in ('title','start'):
            x,y,_,_=pvp.REGIONS[name]
            image.paste(pvp.reference(name),(x-1,y+2))
        self.assertEqual(pvp.stage(image),'ranked')
        image.paste((60,60,60),(990,500,1120,585))
        self.assertFalse(pvp.ranked_visible(image))

    def test_base_entry_with_shift_and_changed_background_is_recognized(self):
        with Image.open(Path('artifacts/validation/pvp/base-entry-shifted.png')) as image:
            image=image.convert('RGB')
        self.assertFalse(pvp.matches(image,'entry'))
        self.assertTrue(pvp.entry_visible(image))
        self.assertEqual(pvp.stage(image),'map')

    def test_base_entry_requires_weapon_icon_and_letters_together(self):
        image=Image.new('RGB',(1366,768),(120,120,120))
        image.paste(pvp.reference('entry'),(790,679))
        self.assertTrue(pvp.entry_visible(image))
        image.paste((120,120,120),(790,679,871,744))
        self.assertFalse(pvp.entry_visible(image))
        self.assertIsNone(pvp.stage(image))

    def test_start_waits_for_base_to_render_after_focus(self):
        image=Image.new('RGB',(1366,768));clock=[0.0]
        with patch.object(pvp,'stage',side_effect=[None,None,'map']), \
             patch.object(pvp.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(pvp.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)), \
             patch.object(pvp.mouse,'click') as click:
            frame,current=pvp.wait_start_stage(lambda:image)
        self.assertIs(frame,image)
        self.assertEqual(current,'map')
        self.assertAlmostEqual(clock[0],.3)
        click.assert_not_called()

    def test_start_timeout_saves_actual_unrecognized_frame(self):
        image=Image.new('RGB',(1366,768));clock=[0.0]
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory, \
             patch.object(pvp,'ROOT',Path(directory)), \
             patch.object(pvp,'stage',return_value=None), \
             patch.object(pvp.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(pvp.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)), \
             patch.object(pvp.mouse,'click') as click:
            with self.assertRaises(RuntimeError): pvp.wait_start_stage(lambda:image,timeout=.3)
            self.assertTrue((Path(directory)/'start-unrecognized.png').exists())
        click.assert_not_called()

    def test_base_wait_does_not_accept_active_battle(self):
        image=Image.new('RGB',(1366,768))
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory, \
             patch.object(pvp,'ROOT',Path(directory)), \
             patch.object(pvp,'stage',return_value='battle'):
            with self.assertRaises(RuntimeError): pvp.wait_start_stage(lambda:image)

    def test_deployment_click_is_cancelled_when_opponent_surrenders(self):
        image=Image.new('RGB',(1366,768));clicks=[]
        with patch.object(pvp,'stage',return_value='victory'):
            capture,click=pvp.deployment_io(lambda:image,clicks.append)
            with self.assertRaises(pvp.DeploymentSettled): click((400,730))
        self.assertEqual(clicks,[])

    def test_surrender_during_deployment_settles_and_finishes_round(self):
        image=Image.new('RGB',(1366,768))
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp,'game_capture',return_value=(lambda:image,lambda p:None,None)))
            stack.enter_context(patch.object(pvp,'stage',return_value='map'))
            stack.enter_context(patch.object(pvp,'start_match',return_value={'status':'deployment'}))
            stack.enter_context(patch.object(pvp,'send_laugh',return_value={'sent':True}))
            stack.enter_context(patch.object(pvp,'deploy_team',side_effect=pvp.DeploymentSettled('victory')))
            finish=stack.enter_context(patch.object(pvp,'finish_defeat',return_value={'returned':'map'}))
            opening=stack.enter_context(patch.object(pvp,'opening_sweep'))
            result=pvp.run_round()
        self.assertEqual(result['status'],'complete')
        self.assertTrue(result['deployment_interrupted'])
        self.assertEqual(result['battle']['outcome'],'victory')
        finish.assert_called_once();opening.assert_not_called()

    def test_laugh_animation_variant_is_located_at_correct_icon(self):
        with Image.open(Path('artifacts/validation/pvp/laugh-animation.png')) as image:
            point=pvp.locate_laugh(image.convert('RGB'))
        self.assertIsNotNone(point)
        self.assertLess(abs(point[0]-401),8)
        self.assertLess(abs(point[1]-144),8)

    def test_laugh_is_not_detected_on_plain_map_background(self):
        self.assertIsNone(pvp.locate_laugh(Image.new('RGB',(1366,768),(170,150,100))))

    def test_continuous_loop_records_finished_rounds_and_stops_on_error(self):
        image=Image.new('RGB',(1366,768))
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp.control,'check'))
            stack.enter_context(patch.object(pvp,'game_capture',return_value=(lambda:image,None,None)))
            stack.enter_context(patch.object(pvp,'stage',return_value='map'))
            run=stack.enter_context(patch.object(pvp,'run_round',side_effect=[
                {'battle':{'outcome':'defeat'}},{'battle':{'outcome':'victory'}},RuntimeError('stop')]))
            with self.assertRaisesRegex(RuntimeError,'stop'): pvp.run_loop()
            import json
            report=json.loads((Path(directory)/'loop-result.json').read_text(encoding='utf-8'))
        self.assertEqual(run.call_count,3)
        self.assertEqual(report['completed'],2)
        self.assertEqual((report['victories'],report['defeats']),(1,1))
        self.assertEqual(report['status'],'stopped')

    def test_batch_finishes_exactly_five_rounds(self):
        image=Image.new('RGB',(1366,768))
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp.control,'check'))
            stack.enter_context(patch.object(pvp,'game_capture',return_value=(lambda:image,None,None)))
            stack.enter_context(patch.object(pvp,'stage',return_value='map'))
            run=stack.enter_context(patch.object(pvp,'run_round',return_value={'status':'complete'}))
            report=pvp.run_batch(5)
        self.assertEqual(run.call_count,5)
        self.assertEqual(report['completed'],5)
        self.assertEqual(report['status'],'complete')

    def test_blue_skill_preview_with_enabled_pass_is_active_battle(self):
        image=Image.new('RGB',(1366,768),(130,225,212))
        ImageDraw.Draw(image).rectangle((30,190,108,216),fill=(240,120,20))
        self.assertTrue(pvp.pass_available(image))
        self.assertTrue(pvp.battle_started(image))

    def test_waiting_opponent_after_selecting_gunner_does_not_click_skill(self):
        image=Image.new('RGB',(1366,768));clicks=[]
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp,'stage',side_effect=['battle','victory','victory']))
            stack.enter_context(patch.object(pvp,'battle_started',side_effect=[True,True,False]))
            stack.enter_context(patch.object(pvp,'our_turn',return_value=True))
            stack.enter_context(patch.object(pvp.deployment,'gunner_present',return_value=True))
            stack.enter_context(patch.object(pvp.time,'sleep'))
            result=pvp.opening_sweep(lambda:image,clicks.append,[599,390])
        self.assertEqual(clicks,[[599,390]])
        self.assertFalse(result['released'])

    def test_opening_clicks_covered_tile_without_sprite_outline_analysis(self):
        image=Image.new('RGB',(1366,768));clicks=[]
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp,'stage',return_value='battle'))
            stack.enter_context(patch.object(pvp,'battle_started',return_value=True))
            stack.enter_context(patch.object(pvp,'our_turn',return_value=True))
            stack.enter_context(patch.object(pvp.deployment,'gunner_present',return_value=True))
            stack.enter_context(patch.object(pvp.combat,'skill_panel_visible',side_effect=[True,False]))
            stack.enter_context(patch.object(pvp.combat,'cooldown',return_value={'blocked':False}))
            outlines=stack.enter_context(patch.object(pvp.combat,'outline_hits'))
            stack.enter_context(patch.object(pvp.time,'sleep'))
            result=pvp.opening_sweep(lambda:image,clicks.append,[599,390])
        self.assertEqual(clicks,[[599,390],pvp.combat.SKILLS[1],[764,306]])
        self.assertTrue(result['released'])
        outlines.assert_not_called()

    def test_team_places_one_gunner_and_six_babies_before_start(self):
        image=Image.new('RGB',(1366,768));draw=ImageDraw.Draw(image)
        draw.rectangle((1200,505,1360,560),fill=(30,170,20))
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp,'stage',return_value='deployment'))
            stack.enter_context(patch.object(pvp,'unit_count',return_value=(0,8)))
            stack.enter_context(patch.object(pvp.deployment,'gunner_present',side_effect=lambda im,p:p==(599,390)))
            place=stack.enter_context(patch.object(pvp,'place_icon',return_value=image))
            clicks=[];result=pvp.deploy_team(lambda:image,clicks.append,(0,0,1366,768))
        self.assertEqual([call.args[3] for call in place.call_args_list],['heavy-gunner-icon.png']+['bigfoot-baby-icon.png']*6)
        self.assertEqual(len(clicks),1)
        self.assertEqual(result['count'],7)

    def test_single_gunner_is_placed_then_started_without_ocr_delay(self):
        image=Image.new('RGB',(1366,768))
        ImageDraw.Draw(image).rectangle((1200,467,1360,517),fill=(30,170,20))
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp,'stage',return_value='deployment'))
            stack.enter_context(patch.object(pvp,'unit_count',side_effect=[(0,8),(5,8)]))
            stack.enter_context(patch.object(pvp.deployment,'find_icon',return_value=(450,730)))
            stack.enter_context(patch.object(pvp.deployment,'gunner_present',side_effect=lambda image,cell:cell==[599,390] or cell==(599,390)))
            stack.enter_context(patch.object(pvp.time,'sleep'))
            ocr=stack.enter_context(patch.object(pvp.app,'recognize'))
            click=stack.enter_context(patch.object(pvp.mouse,'click'))
            result=pvp.deploy_single(lambda:image,click,(0,0,1366,768))
        self.assertEqual(result['count'],1)
        self.assertEqual(click.call_count,1)
        self.assertTrue(result['resumed'])
        self.assertGreater(click.call_args.args[0][0],1200)
        ocr.assert_not_called()

    def test_green_timer_also_identifies_deployment(self):
        image=Image.new('RGB',(1366,768));draw=ImageDraw.Draw(image)
        draw.rectangle((630,4,736,61),outline=(40,150,20),width=4)
        draw.rectangle((1160,18,1210,29),fill=(240,180,10))
        draw.rectangle((1200,505,1360,560),fill=(30,170,20))
        self.assertEqual(pvp.stage(image),'deployment')

    def test_matching_deployment_and_fight_are_one_continuous_round(self):
        image=Image.new('RGB',(1366,768));events=[]
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp,'game_capture',return_value=(lambda:image,lambda p:None,(0,0,1366,768))))
            stack.enter_context(patch.object(pvp,'stage',return_value='map'))
            stack.enter_context(patch.object(pvp,'start_match',side_effect=lambda progress:events.append('match') or {'status':'deployment'}))
            stack.enter_context(patch.object(pvp,'send_laugh',side_effect=lambda *args:events.append('emote') or {'sent':True}))
            stack.enter_context(patch.object(pvp,'deploy_team',side_effect=lambda *args:events.append('deploy') or {'cell':[599,390]}))
            stack.enter_context(patch.object(pvp,'opening_sweep',side_effect=lambda *args:events.append('opening') or {'released':True}))
            stack.enter_context(patch.object(pvp,'lose_battle',side_effect=lambda *args:events.append('lose') or {}))
            result=pvp.run_round()
        self.assertEqual(events,['match','emote','deploy','opening','lose'])
        self.assertEqual(result['status'],'complete')

    def test_pass_checks_every_three_seconds_and_stops_on_defeat(self):
        clock=[0.0];checks=[];states=iter(['battle','battle','defeat'])
        image=Image.new('RGB',(1366,768))
        def classify(frame,**kwargs): checks.append(clock[0]);return next(states)
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp.control,'check'))
            stack.enter_context(patch.object(pvp,'stage',side_effect=classify))
            stack.enter_context(patch.object(pvp,'pass_available',return_value=True))
            stack.enter_context(patch.object(pvp.app,'recognize',return_value=[{'Text':'放弃'}]))
            finish=stack.enter_context(patch.object(pvp,'finish_defeat',return_value={'returned':'map'}))
            stack.enter_context(patch.object(pvp.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(pvp.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
            click=stack.enter_context(patch.object(pvp.mouse,'click'))
            result=pvp.lose_battle(lambda:image,click)
        self.assertEqual(result['passes'],2)
        self.assertEqual(click.call_count,2)
        finish.assert_called_once()
        for actual,expected in zip(checks,[0,3,6]): self.assertAlmostEqual(actual,expected)

    def test_monitor_polls_four_seconds_apart_through_transition(self):
        clock=[0.0];observed=[];states=iter([None,'matching','deployment'])
        image=Image.new('RGB',(1366,768))
        def classify(frame,**kwargs):
            observed.append(clock[0]);return next(states)
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp.control,'check'))
            stack.enter_context(patch.object(pvp,'stage',side_effect=classify))
            stack.enter_context(patch.object(pvp.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(pvp.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
            _,state,_=pvp.monitor_match(lambda:image)
        self.assertEqual(state,'deployment')
        for actual,expected in zip(observed,[4,8,12]): self.assertAlmostEqual(actual,expected)

    def run_flow(self,stages):
        clock=[0.0]
        with tempfile.TemporaryDirectory(dir=pvp.ROOT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(pvp,'ROOT',Path(directory)))
            stack.enter_context(patch.object(pvp.control,'check'))
            stack.enter_context(patch.object(pvp.app,'find_game',return_value=1))
            stack.enter_context(patch.object(pvp.app,'focus_game'))
            stack.enter_context(patch.object(pvp.app,'bounds',return_value=(0,0,1366,768)))
            stack.enter_context(patch.object(pvp.app.user32,'IsIconic',return_value=False))
            stack.enter_context(patch.object(pvp.app.user32,'GetForegroundWindow',return_value=1))
            stack.enter_context(patch.object(pvp.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768))))
            stack.enter_context(patch.object(pvp,'stage',side_effect=stages))
            stack.enter_context(patch.object(pvp.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(pvp.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
            click=stack.enter_context(patch.object(pvp.mouse,'click'))
            result=pvp.start_match()
            return result,[call.args for call in click.call_args_list]

    def test_map_to_ranked_to_match_clicks_once_each(self):
        result,clicks=self.run_flow(['map','ranked','ranked','matching','matching','deployment'])
        self.assertEqual(clicks,[(832,722),(1054,541)])
        self.assertEqual(result['status'],'deployment')
        self.assertEqual(result['poll_interval'],4)
        self.assertEqual(result['observations'],[{'state':'matching'},{'state':'deployment'}])

    def test_unaccepted_entry_click_is_retried_only_on_map(self):
        result,clicks=self.run_flow(['map']*28+['ranked','ranked','battle'])
        self.assertEqual(clicks,[(832,722),(832,722),(1054,541)])
        self.assertEqual(result['entry_attempts'],2)

    def test_entry_transition_to_existing_battle_does_not_click_start(self):
        result,clicks=self.run_flow(['map','battle'])
        self.assertEqual(clicks,[(832,722)])
        self.assertEqual(result['status'],'battle')

    def test_fast_match_is_confirmed_in_battle(self):
        result,clicks=self.run_flow(['map','ranked','ranked','battle'])
        self.assertEqual(result['status'],'battle')
        self.assertEqual(len(clicks),2)

    def test_existing_match_is_not_started_twice(self):
        result,clicks=self.run_flow(['matching','matching','deployment'])
        self.assertTrue(result['already_started'])
        self.assertEqual(clicks,[])

    def test_matching_banner_is_detected(self):
        image=Image.new('RGB',(1366,768))
        image.paste(pvp.reference('matching'),(420,40))
        self.assertEqual(pvp.stage(image),'matching')

    def test_matching_banner_ignores_changed_map_background(self):
        image=Image.new('RGB',(1366,768),(70,140,90))
        reference=pvp.reference('matching')
        for y in range(reference.height):
            for x in range(reference.width):
                color=reference.getpixel((x,y))
                if min(color)>215: image.putpixel((420+x,40+y),color)
        self.assertFalse(pvp.matches(image,'matching'))
        self.assertEqual(pvp.stage(image),'matching')

    def test_pvp_timer_and_start_button_mean_deployment(self):
        image=Image.new('RGB',(1366,768))
        draw=ImageDraw.Draw(image)
        draw.rectangle((630,4,736,61),outline=(230,90,15),width=4)
        draw.rectangle((1160,18,1210,29),fill=(240,180,10))
        draw.rectangle((1200,505,1360,560),fill=(30,170,20))
        self.assertEqual(pvp.stage(image),'deployment')

    def test_battle_timer_and_opponent_confirm_pvp_battle(self):
        image=Image.new('RGB',(1366,768))
        draw=ImageDraw.Draw(image)
        draw.rectangle((630,4,736,61),outline=(230,90,15),width=4)
        draw.rectangle((1160,18,1210,29),fill=(240,180,10))
        self.assertEqual(pvp.stage(image),'battle')

if __name__=='__main__': unittest.main()
