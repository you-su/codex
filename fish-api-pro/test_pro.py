import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import server

class ProTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=(server.STATE,server.DATA,server.KEYS)
        server.DATA=Path(self.tmp.name)/'settings.json'
        server.STATE={'ports':[],'config':{},'activePort':None,'autoSwitch':True,'lastRoute':[]}
        server.KEYS={}
    def tearDown(self):
        server.STATE,server.DATA,server.KEYS=self.old
        self.tmp.cleanup()
    def port(self,name='A'):
        server.action('/api/port',dict(name=name,url='https://example.com/v1',protocol='openai',model='test',key='secret'))
        return server.STATE['ports'][-1]
    def test_import_atomic_and_secret_free(self):
        self.port()
        exported=server.action('/api/export',{})
        self.assertNotIn('secret',str(exported))
        bad=copy.deepcopy(exported);bad['ports'].append(dict(name='bad',url='http://example.com',protocol='openai'))
        with self.assertRaises(ValueError):server.action('/api/import',bad)
        self.assertEqual(len(server.STATE['ports']),1)
        server.action('/api/import',exported)
        self.assertEqual(len(server.STATE['ports']),2)
        self.assertFalse(server.public()['ports'][-1]['hasKey'])
    def test_conversation_context_and_failover(self):
        self.port();self.port('B')
        server.action('/api/session',{'system':'be helpful'})
        sid=server.STATE['sessions'][0]['id']
        response={'choices':[{'message':{'content':'answer'}}],'usage':{'total_tokens':7}}
        with patch.object(server,'remote',side_effect=[ValueError('fail'),response]) as mock:
            server.action('/api/converse',{'id':sid,'message':'first'})
            self.assertEqual(mock.call_count,2)
        self.assertEqual(server.STATE['ports'][1]['tokens'],7)
        with patch.object(server,'remote',return_value=response) as mock:
            server.action('/api/converse',{'id':sid,'message':'second'})
            messages=mock.call_args.args[2]['messages']
            self.assertEqual([m['role'] for m in messages],['system','user','assistant','user'])
        server.action('/api/session',{'id':sid,'delete':True})
        self.assertEqual(server.STATE['sessions'],[])
    def test_failure_does_not_store_message(self):
        self.port();server.action('/api/session',{})
        sid=server.STATE['sessions'][0]['id']
        with patch.object(server,'remote',side_effect=ValueError('fail')):
            with self.assertRaises(ValueError):server.action('/api/converse',{'id':sid,'message':'hello'})
        self.assertEqual(server.STATE['sessions'][0]['messages'],[])
if __name__=='__main__':unittest.main()
