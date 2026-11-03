import tempfile
import unittest
from pathlib import Path
import server as app


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        app.DATA = Path(self.temp.name) / 'settings.json'
        app.STATE = {'ports': [{'id': i, 'name': i, 'model': 'model', 'tokens': 0, 'priority': priority} for i, priority in [('a', 3), ('b', 2), ('c', 1)]], 'activePort': 'a', 'autoSwitch': True, 'lastRoute': []}
        app.KEYS = {i: 'secret' for i in 'abc'}
        self.calls = []
        self.failures = {'a'}
        self.original = app.remote
        def fake(p, path, body):
            self.calls.append(p['id'])
            if p['id'] in self.failures:
                raise ValueError('HTTP 402 insufficient balance')
            return {'choices': [{'message': {'content': 'ok'}}], 'usage': {'total_tokens': 5}}
        app.remote = fake

    def tearDown(self):
        app.remote = self.original
        self.temp.cleanup()

    def test_failover_and_sticky(self):
        self.assertEqual(app.routed_chat('hi')['portName'], 'c')
        self.assertEqual(self.calls, ['a', 'c'])
        self.assertEqual(app.STATE['ports'][2]['tokens'], 5)
        self.calls.clear()
        app.routed_chat('again')
        self.assertEqual(self.calls, ['c'])
        self.assertNotIn('secret', app.DATA.read_text())

    def test_manual_switch(self):
        app.action('/api/routing', {'activePort': 'b'})
        app.routed_chat('hi')
        self.assertEqual(self.calls, ['b'])

    def test_all_fail_once(self):
        self.failures = set('abc')
        with self.assertRaises(ValueError):
            app.routed_chat('hi')
        self.assertEqual(self.calls, ['a', 'c', 'b'])
        self.assertEqual(len(app.STATE['lastRoute']), 3)

    def test_disabled(self):
        app.STATE['autoSwitch'] = False
        with self.assertRaises(ValueError):
            app.routed_chat('hi')
        self.assertEqual(self.calls, ['a'])

    def test_missing_key_skipped(self):
        del app.KEYS['c']
        app.routed_chat('hi')
        self.assertEqual(self.calls, ['a', 'b'])

    def test_delete_active(self):
        app.action('/api/delete', {'ids': ['a']})
        self.assertEqual(app.STATE['activePort'], 'c')

    def test_invalid_priority(self):
        with self.assertRaises(ValueError):
            app.action('/api/routing', {'id': 'b', 'priority': 0})

    def test_bad_response_fallback(self):
        original = app.remote
        app.remote = lambda p, path, body: {} if p['id'] == 'a' else original(p, path, body)
        self.assertEqual(app.routed_chat('hi')['portName'], 'c')

if __name__ == '__main__':
    unittest.main()
