import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from carryon.app_server_bridge import AppServerCatalog


def row(ident, name='Task', **extra):
    return {'id':ident, 'name':name, 'cwd':'/repo', 'createdAt':1, 'updatedAt':2, **extra}


class AppServerPaginationTests(unittest.TestCase):
    def catalog(self, pages):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        catalog=AppServerCatalog(temp.name)
        rpc=Mock(side_effect=pages)
        catalog.bridge=SimpleNamespace(require=lambda:(SimpleNamespace(rpc=rpc),None))
        return catalog,rpc

    def test_small_page_does_not_scan_remaining_history(self):
        catalog,rpc=self.catalog([{'data':[row(str(n)) for n in range(100)],'nextCursor':'next'}])
        self.assertEqual([x['id'] for x in catalog.list(2,3)],['3','4'])
        self.assertEqual(rpc.call_count,1)

    def test_search_and_parent_filter_apply_before_offset_across_pages(self):
        catalog,rpc=self.catalog([
            {'data':[row('child','MATCH',parentThreadId='parent'),row('miss'),row('one','Match')],'nextCursor':'next'},
            {'data':[row('two','match'),row('three','MATCH')],'nextCursor':'more'},
        ])
        self.assertEqual([x['id'] for x in catalog.list(2,1,'MATCH')],['two','three'])
        self.assertEqual(rpc.call_count,2)

    def test_full_catalog_still_loads_every_page_and_repeated_cursor_fails(self):
        catalog,rpc=self.catalog([{'data':[row('one')],'nextCursor':'next'},{'data':[row('two')],'nextCursor':None}])
        self.assertEqual(len(catalog.list(2147483647)),2)
        broken,_=self.catalog([{'data':[],'nextCursor':'same'},{'data':[],'nextCursor':'same'}])
        with self.assertRaisesRegex(ValueError,'游标重复'):broken.list()
