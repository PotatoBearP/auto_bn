"""Virtual-clock stall detection and persistent diagnostic evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import combat
import turn_watchdog


class TurnWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.clock=[0.]
        self.messages=[]
        self.image=Image.new('RGB',(100,80),'blue')
        self.monitor=turn_watchdog.TurnWatchdog(self.root,self.messages.append,
            environment=lambda:{'foreground_window':123},clock=lambda:self.clock[0])

    def test_over_one_minute_records_screen_live_decision_and_raw_files(self):
        (self.root/'enemy-board.txt').write_text('2排 [3:乘员低 100%]',encoding='utf-8')
        (self.root/'combat-result.json').write_text('{"old_report":true}',encoding='utf-8')
        self.monitor.event('select_unit',{'selecting_unit':[599,390],
            'current_combat_report':{'cooldowns':[{'blocked':True}],'chosen':{'skill':1}}})
        self.clock[0]=60
        self.monitor.observe(self.image)
        self.assertFalse(self.monitor.incidents)
        self.clock[0]=60.01
        self.monitor.observe(self.image)
        directory=Path(self.monitor.incidents[0])
        snapshot=json.loads((directory/'snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['reason'],'turn_timeout')
        self.assertEqual(snapshot['stage'],'select_unit')
        self.assertEqual(snapshot['environment']['foreground_window'],123)
        self.assertEqual(snapshot['current_observation']['selecting_unit'],[599,390])
        self.assertIn('cooldowns',snapshot['current_observation']['current_combat_report'])
        with Image.open(directory/'current-screen.png') as image:
            self.assertEqual(image.getpixel((0,0)),(0,0,255))
        self.assertEqual((directory/'enemy-board.txt').read_bytes(),(self.root/'enemy-board.txt').read_bytes())
        self.assertEqual(len(self.messages),1)

    def test_retries_do_not_reset_clock_or_flood_snapshots(self):
        for seconds in (20,40,61,80,120):
            self.clock[0]=seconds
            self.monitor.event('retry',{'retry_reason':'selection pending'})
            self.monitor.observe(self.image)
        self.assertEqual(len(self.monitor.incidents),1)
        self.assertEqual(len(self.messages),1)
        self.monitor.progressed()
        self.clock[0]=179
        self.monitor.observe(self.image)
        self.assertEqual(len(self.monitor.incidents),1)
        self.clock[0]=181
        self.monitor.observe(self.image)
        self.assertEqual(len(self.monitor.incidents),2)
        snapshot=json.loads((Path(self.monitor.incidents[1])/'snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['observed_turn'],2)

    def test_watchdog_runs_inside_long_turn_wait_and_sends_no_input(self):
        token=turn_watchdog.CURRENT.set(self.monitor)
        self.addCleanup(turn_watchdog.CURRENT.reset,token)
        def capture():
            turn_watchdog.observe(self.image)
            return self.image
        def sleep(seconds): self.clock[0]+=seconds
        with patch.object(combat.time,'monotonic',side_effect=lambda:self.clock[0]), \
             patch.object(combat.time,'sleep',side_effect=sleep), \
             patch.object(combat,'settlement_phase',return_value=None), \
             patch.object(combat,'skill_panel_visible',return_value=False), \
             patch.object(combat.mouse,'click') as click:
            _,turn=combat.wait_our_turn(capture,require_transition=True,timeout=65)
        self.assertFalse(turn['our_turn'])
        self.assertEqual(len(self.monitor.incidents),1)
        click.assert_not_called()

    def test_evidence_failure_does_not_stop_battle(self):
        self.clock[0]=61
        with patch.object(self.image,'save',side_effect=OSError('image unavailable')):
            self.monitor.observe(self.image)
        snapshot=json.loads((Path(self.monitor.incidents[0])/'snapshot.json').read_text(encoding='utf-8'))
        self.assertTrue(snapshot['capture_errors'])
        self.assertEqual(len(self.messages),1)


if __name__=='__main__': unittest.main()
