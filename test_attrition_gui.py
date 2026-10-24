"""GUI count reaches the real attrition worker and restores completion status."""
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import app


class AttritionGuiTests(unittest.TestCase):
    def instance(self,value):
        instance=app.App.__new__(app.App)
        instance.attrition_rounds=Mock();instance.attrition_rounds.get.return_value=value
        instance.root=Mock();instance.stop_button=Mock();instance.messages=queue.Queue()
        instance.set_status=Mock();instance.action_buttons=Mock(return_value=[])
        return instance

    def run_worker(self,value,expected):
        instance=self.instance(value)
        report={'battles':[{}]*5,'opening_checks':[{'rerolls':[{}]}]}
        with patch.object(app.control,'reset'), \
             patch.object(app.threading,'Thread',side_effect=lambda target,daemon:SimpleNamespace(start=target)), \
             patch('attrition.run_loop',return_value=report) as run:
            instance.run_attrition()
        self.assertEqual(run.call_args.kwargs['max_battles'],expected)
        message=instance.messages.get_nowait()
        self.assertIn('5 轮',message)
        self.assertIn('重开 1 次',message)
        instance.root.iconify.assert_called_once()

    def test_five_rounds(self): self.run_worker('5',5)
    def test_zero_runs_continuously(self): self.run_worker('0',None)
    def test_invalid_count_never_starts(self):
        instance=self.instance('-1')
        with patch('attrition.run_loop') as run: instance.run_attrition()
        run.assert_not_called()
        instance.root.iconify.assert_not_called()

if __name__=='__main__': unittest.main()
