"""Run real loop/automation/settlement together against a deterministic desktop."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
import app
import attrition
import attrition_settlement
import automation
import combat
import control
import deployment
import formation
import settlement
import sweep
import target_priority

class CycleTests(unittest.TestCase):
    def run_case(self,dialogs=('defeat',),direct=False,stuck=False,focus_loss=False,rounds=1):
        clock=[0.];state=['deployment'];events=[];starts=[];clicks=[]
        palettes={'deployment':20,'battle':40,'defeat':60,'experience':80,'loot2':100,'map':120}
        def capture(**kwargs):
            frame=Image.new('RGB',(1366,768),(palettes[state[0]],)*3)
            if state[0]=='deployment': frame.paste((20,180,20),(1200,450,1360,570))
            return frame
        def dialog(frame):
            name=next(name for name,value in palettes.items() if frame.getpixel((0,0))[0]==value)
            if name not in dialogs: return None,None
            return ('experience' if name=='experience' else 'loot'),(726,495,946,537)
        def step():
            self.assertEqual(state[0],'battle')
            self.assertTrue(target_priority.ATTRITION.get())
            events.append('attack');state[0]=dialogs[0]
            return {'released':True,'release_confirmed':True,'settled':True,'battle_ended':True,
                    'chosen':{'unit':[378,280],'skill':1,'target':[544,196],'hit_count':1}}
        def click(x,y):
            if state[0]=='deployment':
                starts.append(True);events.append('start');state[0]='battle'
                return
            clicks.append(state[0]);events.append('confirm:'+state[0])
            if stuck: return
            index=dialogs.index(state[0])+1
            state[0]=dialogs[index] if index<len(dialogs) else ('battle' if direct else 'deployment')
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory)
            for module in (sweep,automation,settlement,attrition_settlement):
                stack.enter_context(patch.object(module,'COMBAT',root))
            stack.enter_context(patch.object(deployment,'ROOT',root))
            stack.enter_context(patch.object(control,'check'))
            stack.enter_context(patch.object(app,'find_game',return_value=1))
            stack.enter_context(patch.object(app,'focus_game'))
            stack.enter_context(patch.object(app,'bounds',return_value=(0,0,1366,768)))
            stack.enter_context(patch.object(app.user32,'IsIconic',return_value=False))
            stack.enter_context(patch.object(app.user32,'GetForegroundWindow',
                side_effect=lambda:2 if focus_loss and clicks else 1))
            stack.enter_context(patch.object(sweep.ImageGrab,'grab',side_effect=capture))
            stack.enter_context(patch.object(settlement,'dialog',side_effect=dialog))
            stack.enter_context(patch.object(settlement,'map_visible',return_value=False))
            stack.enter_context(patch.object(deployment,'start_button_visible',
                side_effect=lambda frame:frame.getpixel((0,0))[0]==20))
            stack.enter_context(patch.object(combat,'skill_panel_visible',
                side_effect=lambda frame:frame.getpixel((0,0))[0]==40))
            stack.enter_context(patch.object(attrition_settlement,'pass_available',
                side_effect=lambda frame:frame.getpixel((0,0))[0]==40))
            stack.enter_context(patch.object(deployment,'locate_start_button',
                return_value=((1280,510),(1200,450,1360,570),'Start')))
            stack.enter_context(patch('unit_ai.coward.CowardAI.present',return_value=True))
            deploy=stack.enter_context(patch.object(deployment,'deploy_formation',return_value=[]))
            start=stack.enter_context(patch.object(deployment,'start_battle',wraps=deployment.start_battle))
            stack.enter_context(patch.object(combat,'combat_step',side_effect=step))
            reset=stack.enter_context(patch.object(combat,'reset_battle_state'))
            stack.enter_context(patch.object(formation,'activate'))
            stack.enter_context(patch.object(attrition_settlement.mouse,'click',side_effect=click))
            stack.enter_context(patch.object(attrition_settlement.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(attrition_settlement.time,'sleep',
                side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
            monitor=Mock();monitor.incidents=[]
            stack.enter_context(patch.object(automation.turn_watchdog,'TurnWatchdog',return_value=monitor))
            if stuck or focus_loss:
                with self.assertRaises(RuntimeError): attrition.run_loop(max_battles=rounds)
                report=json.loads((root/'attrition-result.json').read_text(encoding='utf-8'))
                self.assertEqual(report['status'],'stopped')
                self.assertEqual(len(starts),1)
                self.assertEqual(len(clicks),1 if focus_loss else 3)
            else:
                result=attrition.run_loop(max_battles=rounds)
                self.assertEqual(result['status'],'complete')
                self.assertEqual(len(result['battles']),rounds)
                self.assertEqual(len(starts),1 if direct else rounds+1)
                self.assertEqual(len(clicks),len(dialogs)*rounds)
                deploy.assert_called_once_with(attrition.CONFIG)
                self.assertEqual(reset.call_count,rounds+1)
                self.assertNotIn('verify_placement',start.call_args_list[0].kwargs)
                for call in start.call_args_list[1:]: self.assertFalse(call.kwargs['verify_placement'])
                self.assertEqual(events[:2],['start','attack'])
                if not direct: self.assertEqual(events[-1],'start')
                for battle in result['battles']:
                    self.assertTrue(battle['actions'][0]['confirmed'])
                    self.assertEqual(len(battle['settlement']['confirmed']),len(dialogs))
                    if not direct: self.assertTrue(battle['next_start']['start_button_disappeared'])
                self.assertEqual(state[0],'battle')
            self.assertFalse(target_priority.ATTRITION.get())

    def test_defeat_single_confirm_then_next_start(self): self.run_case()
    def test_defeat_experience_then_next_start(self): self.run_case(('defeat','experience'))
    def test_multiple_same_title_dialogs_are_each_confirmed(self): self.run_case(('defeat','loot2','experience'))
    def test_two_complete_rounds(self): self.run_case(('defeat','experience'),rounds=2)
    def test_victory_experience_then_next_start(self): self.run_case(('loot2','experience'))
    def test_auto_started_next_battle(self): self.run_case(direct=True)
    def test_stuck_confirm_stops_without_starting(self): self.run_case(stuck=True)
    def test_focus_loss_stops_without_clicking_next(self): self.run_case(focus_loss=True)

if __name__=='__main__': unittest.main()
