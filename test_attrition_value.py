"""Maximize real hit count before preferring recognized red valuable units."""
import unittest
import target_priority as priority
from combat_planner import plan
from unit_ai import get


def enemy(row,column,sprite='crew',hp=1.):
    return {'row':row,'column':column,'sprite':sprite,'hp_fraction':hp,'hp_source':'health_bar'}


class ValueTests(unittest.TestCase):
    def setUp(self):
        token=priority.ATTRITION.set(True)
        self.addCleanup(priority.ATTRITION.reset,token)

    def test_three_normal_targets_beat_two_red_targets(self):
        normal=[enemy(row,2) for row in (1,2,3)]
        red=[enemy(1,4,'brute',.1),enemy(2,4,'wing',.1)]
        self.assertGreater(priority.attack_key(normal,len),priority.attack_key(red,len))

    def test_equal_coverage_prefers_more_red_targets(self):
        red=[enemy(1,2,'brute'),enemy(2,2,'wing')]
        wounded=[enemy(1,4,hp=.1),enemy(2,4,hp=.1)]
        self.assertGreater(priority.attack_key(red,len),priority.attack_key(wounded,len))

    def test_equal_value_keeps_finishing_tiebreak(self):
        full=[enemy(1,2,'brute'),enemy(2,2)]
        weak=[enemy(1,4,'brute',.1),enemy(2,4)]
        self.assertGreater(priority.attack_key(weak,len),priority.attack_key(full,len))

    def test_rubble_and_humanoid_air_units_never_add_coverage_or_value(self):
        hits=[{'kind':'obstacle','sprite':'brute'},enemy(1,2,'airflyer')]
        self.assertEqual(priority.attack_key(hits,len),(0,0,0,0))
        self.assertFalse(priority.high_value({'sprite':'stone'}))
        self.assertFalse(priority.high_value({'sprite':'unknown','outline':'red'}))

    def test_planner_chooses_three_target_column_with_more_red_units(self):
        enemies=[enemy(row,2) for row in (1,2,3)]
        enemies += [enemy(1,4,'brute'),enemy(2,4,'wing'),enemy(3,4)]
        options=plan({(378,280):get('coward')},enemies,{(378,280):(1,2)})
        self.assertEqual(options[0]['anchor'],[1,4])
        self.assertEqual(options[0]['hit_count'],3)
        self.assertEqual(options[0]['priority_key'][:2],(3,2))

if __name__=='__main__': unittest.main()
