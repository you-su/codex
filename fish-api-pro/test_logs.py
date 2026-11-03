import tempfile, unittest
from pathlib import Path
import server as app
class LogTests(unittest.TestCase):
 def test_persistence_bound_and_private_content(self):
  original=app.DATA
  with tempfile.TemporaryDirectory() as d:
   try:
    app.DATA=Path(d)/'settings.json'
    folder=app.DATA.parent/'logs';folder.mkdir()
    entries=[{'time':'','level':'INFO','event':'test','detail':''}]*1000
    (folder/'runtime.json').write_text(app.json.dumps(entries))
    app.log_event('WARN','测试','受控详情')
    self.assertEqual(len(app.read_logs()),1000)
    self.assertEqual(app.read_logs()[-1]['level'],'WARN')
    with self.assertRaises(ValueError):app.action('/invalid',{'key':'sensitive-secret','message':'private-message'})
    raw=(folder/'runtime.json').read_text()
    self.assertNotIn('sensitive-secret',raw);self.assertNotIn('private-message',raw)
   finally:app.DATA=original
