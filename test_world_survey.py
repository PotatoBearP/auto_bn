import unittest
from unittest.mock import Mock
import numpy as np
from PIL import Image
from world_survey import WorldSurvey,motion_score,drag_source


class WorldSurveyTests(unittest.TestCase):
    def test_camera_movement_is_not_confused_with_small_animation(self):
        rng=np.random.default_rng(42)
        data=rng.integers(0,256,(768,1366,3),dtype=np.uint8)
        before=Image.fromarray(data)
        altered=data.copy();altered[200:220,300:320]=0
        self.assertLess(motion_score(before,Image.fromarray(altered)),2.5)
        self.assertGreater(motion_score(before,Image.fromarray(np.roll(data,70,axis=1))),2.5)

    def test_pan_stays_inside_client_and_avoids_card_fill(self):
        image=Image.new('RGB',(1366,768),(60,140,190))
        for delta in ((600,0),(-600,0),(0,350),(0,-350)):
            x,y=drag_source(image,*delta)
            self.assertTrue(110<=x+delta[0]<=1250)
            self.assertTrue(100<=y+delta[1]<=665)
        with self.assertRaises(RuntimeError): drag_source(Image.new('RGB',(1366,768),(190,150,20)),600,0)

    def test_serpentine_changes_direction_only_after_row_boundary(self):
        survey=WorldSurvey((0,0,1366,768),Mock())
        survey.pan=Mock(side_effect=[True,False,True,False,True,False,True,False,False])
        self.assertTrue(survey.next_view())
        self.assertTrue(survey.next_view())
        self.assertTrue(survey.next_view())
        self.assertFalse(survey.next_view())
        self.assertEqual(survey.direction,1)
