"""Spend wounded cowards' usable skills before healthy units' skills."""
import unittest
import formation
import target_priority
import test_coward as coward_tests
from combat_planner import plan


class LowHealthCowardTests(unittest.TestCase):
    def setUp(self):
        token=target_priority.ATTRITION.set(True)
        self.addCleanup(target_priority.ATTRITION.reset,token)
        self.case=coward_tests.CowardTests();self.case.setUp()
        self.points=[formation.position(1,c) for c in (1,3,5)]
        self.controllers=dict.fromkeys(self.points,self.case.ai)

    def test_wounded_right_coward_acts_before_left_and_middle(self):
        left,middle,right=self.points
        result=self.case.preview_case([coward_tests.enemy(1,3)],self.controllers,
            health={left:.9,middle:.6,right:.1})
        self.assertEqual(result['chosen']['unit'],list(right))
        self.assertEqual(result['chosen']['unit_hp_fraction'],.1)
        self.assertEqual(self.case.input_clicks[0],right)

    def test_wounded_unit_uses_ready_second_skill_before_healthy_units(self):
        left,middle,right=self.points
        enemies=[coward_tests.enemy(row,2) for row in (1,2,3)]
        result=self.case.preview_case(enemies,self.controllers,
            health={left:.9,middle:.6,right:.1},blocked={(right,1)})
        self.assertEqual(result['chosen']['unit'],list(right))
        self.assertEqual(result['chosen']['skill'],2)

    def test_both_skills_blocked_falls_back_to_next_lowest_health(self):
        left,middle,right=self.points
        result=self.case.preview_case([coward_tests.enemy(1,3)],self.controllers,
            health={left:.9,middle:.6,right:.1},blocked={(right,1),(right,2)})
        self.assertEqual(result['chosen']['unit'],list(middle))

    def test_unknown_health_does_not_outrank_observed_wounded_unit(self):
        left,middle,right=self.points
        result=self.case.preview_case([coward_tests.enemy(1,3)],self.controllers,health={right:.3})
        self.assertEqual(result['chosen']['unit'],list(right))

    def test_same_health_keeps_finishing_then_coverage(self):
        enemies=[coward_tests.enemy(1,2,.2),coward_tests.enemy(2,3),coward_tests.enemy(3,3)]
        options=plan(self.controllers,enemies,{p:(1,2) for p in self.points},
                     ally_health=dict.fromkeys(self.points,.5))
        self.assertEqual(options[0]['priority_key'],max(option['priority_key'] for option in options))

    def test_each_plan_uses_fresh_observed_health(self):
        left,middle,right=self.points
        enemies=[coward_tests.enemy(1,3)]
        skills={p:(1,2) for p in self.points}
        first=plan(self.controllers,enemies,skills,ally_health={left:.1,right:.8})
        second=plan(self.controllers,enemies,skills,ally_health={left:.9,right:.2})
        self.assertEqual(first[0]['unit'],list(left))
        self.assertEqual(second[0]['unit'],list(right))

    def test_ordinary_battle_keeps_existing_order(self):
        token=target_priority.ATTRITION.set(False)
        try:
            left,middle,right=self.points
            result=self.case.preview_case([coward_tests.enemy(1,3)],self.controllers,
                health={left:.9,middle:.6,right:.1})
            self.assertEqual(result['chosen']['unit'],list(left))
        finally: target_priority.ATTRITION.reset(token)

if __name__=='__main__': unittest.main()
