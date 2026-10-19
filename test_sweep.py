"""Sweep repeats without searching or deploying again; no desktop input."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import control
import formation
import settlement
import sweep
from paths import COMBAT


class SweepTests(unittest.TestCase):
    def test_default_and_custom_sweep_formation_are_independent(self):
        self.assertEqual(formation.sweep_defaults()['units'],[
            {'row':1,'column':3,'unit':'heavy_gunner'}])
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory, \
             patch.object(formation,'SWEEP_PATH',Path(directory)/'sweep.json'), \
             patch.object(formation,'CONFIG_PATH',Path(directory)/'normal.json'):
            self.assertEqual(formation.load_sweep(),formation.sweep_defaults())
            formation.save(formation.defaults())
            formation.save_sweep({'version':1,'units':[{'row':2,'column':2,'unit':'heavy_gunner'}]})
            self.assertEqual(formation.load(),formation.defaults())
            self.assertEqual(formation.load_sweep()['units'][0]['row'],2)

    def run_loop_case(self,failure=None,retained=False,resume=False):
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(sweep,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(control,'check'))
            stack.enter_context(patch.object(sweep.app,'find_game',return_value=1))
            stack.enter_context(patch.object(sweep.app,'focus_game'))
            stack.enter_context(patch.object(sweep.app,'bounds',return_value=(0,0,1366,768)))
            stack.enter_context(patch.object(sweep.app.user32,'IsIconic',return_value=False))
            stack.enter_context(patch.object(sweep.app.user32,'GetForegroundWindow',return_value=1))
            stack.enter_context(patch.object(sweep.ImageGrab,'grab',return_value=Image.new('RGB',(1366,768))))
            stack.enter_context(patch.object(sweep.deployment,'locate_start_button'))
            stack.enter_context(patch.object(sweep.deployment,'start_button_visible',return_value=not resume))
            stack.enter_context(patch.object(sweep.settlement,'phase',return_value=None))
            stack.enter_context(patch.object(sweep.combat,'skill_panel_visible',return_value=True))
            stack.enter_context(patch.object(formation,'active',return_value=formation.sweep_defaults()))
            deploy=stack.enter_context(patch.object(sweep.deployment,'deploy_formation',return_value=[]))
            start=stack.enter_context(patch.object(sweep.deployment,'start_battle',return_value={}))
            battle=stack.enter_context(patch.object(sweep.automation,'run_battle',
                return_value={'actions':[],'settlement':{'next_battle_ready':not retained,
                              'next_deployment_ready':retained}},side_effect=failure))
            search=stack.enter_context(patch.object(sweep.app,'encounter',side_effect=AssertionError('No search')))
            reset=stack.enter_context(patch.object(sweep.combat,'reset_battle_state'))
            stack.enter_context(patch.object(formation,'activate'))
            if failure:
                with self.assertRaises(RuntimeError):
                    sweep.run_loop(max_battles=2,config=formation.sweep_defaults())
            else:
                result=sweep.run_loop(max_battles=2,config=formation.sweep_defaults())
                self.assertEqual(len(result['battles']),2)
                self.assertEqual(result['status'],'complete')
                self.assertEqual(reset.call_count,0 if retained else 2)
            if resume: deploy.assert_not_called()
            else: deploy.assert_called_once_with(formation.sweep_defaults())
            self.assertEqual(start.call_count,(2 if retained and not failure else 0)+int(not resume))
            for call in start.call_args_list: self.assertEqual(call.args,(formation.sweep_defaults(),))
            for index,call in enumerate(start.call_args_list):
                if not resume and index==0:
                    self.assertNotIn('verify_placement',call.kwargs)
                else:
                    self.assertFalse(call.kwargs['verify_placement'])
            search.assert_not_called()
            for call in battle.call_args_list:
                self.assertTrue(call.kwargs['start_current'])
                self.assertEqual(call.kwargs['settlement_mode'],'repeat')
            self.assertEqual(battle.call_count,1 if failure else 2)

    def test_only_first_battle_deploys_and_every_battle_uses_repeat_settlement(self):
        self.run_loop_case()

    def test_stop_does_not_start_another_battle(self):
        self.run_loop_case(RuntimeError('stopped'))

    def test_retained_formation_only_clicks_start_for_later_battles(self):
        self.run_loop_case(retained=True)

    def test_current_battle_resumes_without_initial_deployment(self):
        self.run_loop_case(resume=True)

    def test_two_confirmations_then_next_battle_instead_of_world_map(self):
        clock=[0.];state=['loot'];clicks=[];image=Image.new('RGB',(1366,768))
        def dialog(frame):
            return (state[0],settlement.REGIONS[state[0]+'-confirm']) if state[0]!='battle' else (None,None)
        def click(x,y):
            clicks.append(state[0]);state[0]='experience' if state[0]=='loot' else 'battle'
        with tempfile.TemporaryDirectory(dir=COMBAT) as directory,ExitStack() as stack:
            stack.enter_context(patch.object(settlement,'COMBAT',Path(directory)))
            stack.enter_context(patch.object(control,'check'))
            stack.enter_context(patch.object(settlement.app,'find_game',return_value=1))
            stack.enter_context(patch.object(settlement.app,'focus_game'))
            stack.enter_context(patch.object(settlement.app,'bounds',return_value=(0,0,1366,768)))
            stack.enter_context(patch.object(settlement.app.user32,'IsIconic',return_value=False))
            stack.enter_context(patch.object(settlement.app.user32,'GetForegroundWindow',return_value=1))
            stack.enter_context(patch.object(settlement.ImageGrab,'grab',return_value=image))
            stack.enter_context(patch.object(settlement,'dialog',side_effect=dialog))
            stack.enter_context(patch.object(settlement,'map_visible',return_value=False))
            stack.enter_context(patch('combat.skill_panel_visible',side_effect=lambda frame:state[0]=='battle'))
            stack.enter_context(patch('deployment.start_button_visible',
                side_effect=lambda frame:state[0]=='battle' and clock[0]>=3))
            stack.enter_context(patch.object(settlement.mouse,'click',side_effect=click))
            stack.enter_context(patch.object(settlement.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(settlement.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
            result=settlement.finish_battle(next_battle=True)
        self.assertEqual(clicks,['loot','experience'])
        self.assertEqual(result['confirmed'],['loot','experience'])
        self.assertFalse(result['next_battle_ready'])
        self.assertTrue(result['next_deployment_ready'])
        self.assertFalse(result['returned_to_map'])
        self.assertGreaterEqual(clock[0],3.35)


if __name__=='__main__': unittest.main()
