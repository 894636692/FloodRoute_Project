import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
ROOT=Path(__file__).resolve().parents[1]

class UITests(unittest.TestCase):
    def test_real_and_simulated_controls(self):
        app=AppTest.from_file(str(ROOT/'src/floodroute/ui/app.py'),default_timeout=60).run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.metric),6)
        app.sidebar.selectbox[0].select('SIMULATED_SCENARIO').run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.metric),6)
        app.sidebar.selectbox[2].select('trusted').run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(app.warning)
        app.sidebar.number_input[2].set_value(0.).run()
        self.assertTrue(app.error)
        self.assertEqual(len(app.exception),0)
