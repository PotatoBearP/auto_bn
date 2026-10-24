"""Opening rerolls must enter combat before every white-flag click."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import attrition_opening as opening
import attrition_vision


class OpeningTests(unittest.TestCase):
    def simulate(self,counts,never_battle=False,lose_focus=False):
        clock=[0.];board=[0];state=['loading'];events=['start'];started=[0.]
        def frame():
            if state[0]=='loading' and not never_battle and clock[0]-started[0]>=.4:
                state[0]='battle'
            image=Image.new('RGB',(1366,768))
            image.info.update(phase=state[0],count=counts[board[0]])
            return image
        def click(x,y):
            if (x,y)==(40,130):
                self.assertEqual(state[0],'battle')
                events.append('flag');state[0]='retreat_menu'
            elif (x,y)==(85,140):
                self.assertEqual(state[0],'retreat_menu')
                events.append('retreat');state[0]='retreat_confirm'
            elif (x,y)==(670,555):
                self.assertEqual(state[0],'retreat_confirm')
                events.append('confirm');board[0]+=1;state[0]='deployment'
            else: self.fail('Unexpected input')
        def start(*args,**kwargs):
            self.assertEqual(state[0],'deployment')
            events.append('start');state[0]='loading';started[0]=clock[0]
        initial=Image.new('RGB',(1366,768));initial.info['count']=counts[0]
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            stack.enter_context(patch.object(opening,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(opening.app,'find_game',return_value=1))
            stack.enter_context(patch.object(opening.app,'bounds',return_value=(0,0,1366,768)))
            stack.enter_context(patch.object(opening.app.user32,'GetForegroundWindow',return_value=2 if lose_focus else 1))
            stack.enter_context(patch.object(opening.control,'check'))
            stack.enter_context(patch.object(opening.ImageGrab,'grab',side_effect=lambda **kwargs:frame()))
            stack.enter_context(patch.object(opening,'battle_ready',side_effect=lambda image:image.info['phase']=='battle'))
            stack.enter_context(patch.object(opening,'retreat_button_visible',side_effect=lambda image:image.info['phase']=='retreat_menu'))
            stack.enter_context(patch.object(opening,'retreat_confirm_visible',side_effect=lambda image:image.info['phase']=='retreat_confirm'))
            stack.enter_context(patch.object(opening.attrition_vision,'air_cells',
                side_effect=lambda image:[(1,c) for c in range(1,image.info['count']+1)]))
            stack.enter_context(patch.object(opening.deployment,'start_button_visible',
                side_effect=lambda image:image.info['phase']=='deployment'))
            stack.enter_context(patch.object(opening.settlement,'phase',return_value=None))
            stack.enter_context(patch.object(opening.deployment,'start_battle',side_effect=start))
            stack.enter_context(patch.object(opening.formation,'active',return_value={}))
            stack.enter_context(patch.object(opening.mouse,'click',side_effect=click))
            stack.enter_context(patch.object(opening.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(opening.time,'sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
            if never_battle or lose_focus:
                with self.assertRaises(RuntimeError): opening.prepare(initial)
                self.assertNotIn('flag',events)
                return
            result=opening.prepare(initial)
        self.assertEqual(events,['start']+['flag','retreat','confirm','start']*(len(counts)-1))
        self.assertEqual(len(result['rerolls']),len(counts)-1)
        self.assertTrue(result['accepted'])

    def test_zero_keeps_lineup(self): self.simulate([0])
    def test_one_keeps_lineup(self): self.simulate([1])
    def test_two_starts_then_rerolls(self): self.simulate([2,1])
    def test_every_rejected_lineup_enters_battle(self): self.simulate([3,2,0])
    def test_loading_never_authorizes_white_flag(self): self.simulate([2],never_battle=True)
    def test_focus_loss_never_clicks_white_flag(self): self.simulate([2],lose_focus=True)

    def test_live_board_counts_humanoid_air_units_only(self):
        with Image.open('assets/fixtures/attrition-deployment.png') as image:
            self.assertEqual(attrition_vision.air_cells(image),[])
        with Image.open('assets/fixtures/attrition-deployment-2.png') as image:
            self.assertEqual(set(attrition_vision.air_cells(image)),{(1,4),(2,1)})

    def test_real_loading_and_deployment_are_not_battle(self):
        for path in ('assets/fixtures/attrition-loading.png','assets/fixtures/attrition-deployment-2.png'):
            with Image.open(path) as image: self.assertFalse(opening.battle_ready(image))

    def test_spread_and_folded_wings_both_count_two(self):
        for name in ('1','3','6'):
            with Image.open(f'assets/fixtures/attrition-air-animation-{name}.png') as image:
                self.assertEqual(set(attrition_vision.air_cells(image)),{(1,4),(2,1)})

    def test_multiframe_merge_tolerates_alternating_detection(self):
        image=Image.new('RGB',(1366,768))
        with patch.object(opening.attrition_vision,'air_cells',side_effect=[[(1,4)],[(2,1)],[(1,4)],[(2,1)]]), \
             patch.object(opening.time,'sleep'):
            self.assertEqual(opening.scan_air(lambda:image,image),[(1,4),(2,1)])

    def test_real_reroll_frame_is_in_battle_and_has_two_air_units(self):
        with Image.open('assets/fixtures/attrition-reroll-before.png') as image:
            self.assertTrue(opening.battle_ready(image))
            self.assertEqual(set(attrition_vision.air_cells(image)),{(1,4),(2,1)})

    def test_real_retreat_menu_and_confirmation_are_distinct_from_pass(self):
        with Image.open('assets/fixtures/attrition-retreat-menu.png') as image:
            self.assertTrue(opening.retreat_button_visible(image))
            self.assertFalse(opening.retreat_confirm_visible(image))
        with Image.open('assets/fixtures/attrition-retreat-confirm.png') as image:
            self.assertTrue(opening.retreat_confirm_visible(image))
            self.assertFalse(opening.battle_ready(image))

if __name__=='__main__': unittest.main()
