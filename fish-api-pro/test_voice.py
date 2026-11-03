import io, wave, tempfile, unittest
from pathlib import Path
import server as app

def wav(seconds):
    b=io.BytesIO()
    with wave.open(b,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*int(seconds*16000))
    return b.getvalue()

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_data=app.DATA;self.old_state=app.STATE
        app.DATA=Path(self.temp.name)/'settings.json';app.STATE={'ports':[]}
    def tearDown(self):
        app.DATA=self.old_data;app.STATE=self.old_state;self.temp.cleanup()
    def test_save_replace_and_independent_targets(self):
        app.store_voice('qq',wav(1),'my voice.mp3');old=app.STATE['voices']['qq']['file']
        app.store_voice('pet',wav(2),'pet.wav');app.store_voice('qq',wav(3),'new.wav')
        self.assertFalse((app.DATA.parent/'voices'/old).exists())
        self.assertEqual(app.STATE['voices']['pet']['duration'],2)
        self.assertEqual(app.STATE['voices']['qq']['duration'],3)
        self.assertTrue(app.DATA.exists())
    def test_exact_limit(self):
        app.store_voice('qq',wav(900),'limit.wav')
        self.assertEqual(app.STATE['voices']['qq']['duration'],900)
    def test_over_limit_preserves_previous(self):
        app.store_voice('qq',wav(1),'original.wav')
        with self.assertRaises(ValueError):app.store_voice('qq',wav(900.1),'long.wav')
        self.assertEqual(app.STATE['voices']['qq']['name'],'original.wav')
    def test_invalid_and_empty(self):
        for raw in [b'not audio',wav(0),wav(1)[:-100]]:
            with self.assertRaises(ValueError):app.store_voice('qq',raw,'bad')
    def test_invalid_target(self):
        with self.assertRaises(ValueError):app.store_voice('../escape',wav(1),'bad')
