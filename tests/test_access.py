import sys,unittest
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from floodroute.routing.access import motor_edges

class AccessTests(unittest.TestCase):
    def test_explicit_restrictions_and_higher_priority_override(self):
        data=pd.DataFrame({'highway':['footway','construction','primary','primary','service','primary'],
            'osm_tags_json':['{}','{}','{"access":"private"}','{"access":"no","motorcar":"yes"}',
                             '{"motor_vehicle:conditional":"yes @ (Mo-Fr)"}','{}']})
        self.assertEqual(motor_edges(data).index.tolist(),[3,5])
