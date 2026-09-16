import unittest
import fitz
from drive_batches import FOLDER_MIME, PDF_MIME, batch_record, combine_pdfs, file_versions, list_batches, list_children


class BatchTests(unittest.TestCase):
    def test_stable_order_and_revisions(self):
        a = {'id':'a','name':'First.pdf','modifiedTime':'1','size':'20'}
        b = {'id':'b','name':'Second.pdf','modifiedTime':'1','size':'20'}
        item = {'id':'folder','name':'1.10 Exit Ticket'}
        self.assertEqual(file_versions([b,a]),file_versions([a,b]))
        self.assertEqual(batch_record(item,[b,a])['id'],batch_record(item,[a,b])['id'])
        self.assertNotEqual(batch_record(item,[a])['id'],batch_record(item,[a,b])['id'])
        self.assertNotEqual(batch_record(item,[a])['id'],batch_record(item,[{**a,'modifiedTime':'2'}])['id'])

    def test_continuous_pages_preserve_content(self):
        documents=[]
        for names in [('A','B'),('C',)]:
            with fitz.open() as d:
                for name in names:
                    p=d.new_page(); p.insert_text((30,30),name)
                documents.append(d.tobytes())
        with fitz.open(stream=combine_pdfs(documents),filetype='pdf') as d:
            self.assertEqual(len(d),3)
            self.assertEqual([p.get_text().strip() for p in d],['A','B','C'])
        self.assertEqual(combine_pdfs(documents[:1]),documents[0])
        with self.assertRaises(ValueError): combine_pdfs([])

    def test_inventory_pagination(self):
        class Response:
            def __init__(self,data): self.data=data
            def raise_for_status(self): pass
            def json(self): return self.data
        class Drive:
            def get(self,url,params,**kwargs):
                if params.get('pageToken') == 'next': return Response({'files':[{'id':'b'}]})
                return Response({'files':[{'id':'a'}],'nextPageToken':'next'})
        self.assertEqual(list_children(Drive(),'folder'),[{'id':'a'},{'id':'b'}])

    def test_folder_batches_and_legacy_files(self):
        class Response:
            def __init__(self,files): self.files=files
            def raise_for_status(self): pass
            def json(self): return {'files':self.files}
        class Drive:
            def get(self,url,params,**kwargs):
                if params['q'].startswith("'root'"):
                    return Response([
                        {'id':'f10','name':'1.10 Exit Ticket','mimeType':FOLDER_MIME},
                        {'id':'f2','name':'1.2 Exit Ticket','mimeType':FOLDER_MIME},
                        {'id':'empty','name':'Empty','mimeType':FOLDER_MIME},
                        {'id':'old','name':'1.1 Exit Ticket.pdf','mimeType':PDF_MIME},
                        {'id':'other','name':'Notes','mimeType':'text/plain'},
                    ])
                children = [
                    {'id':'a','name':'Part A.pdf','mimeType':PDF_MIME,'parents':['f2']},
                    {'id':'b','name':'Part B.pdf','mimeType':PDF_MIME,'parents':['f2']},
                    {'id':'c','name':'Scan.pdf','mimeType':PDF_MIME,'parents':['f10']},
                ]
                return Response([f for f in children if f"'{f['parents'][0]}' in parents" in params['q']])
        batches=list_batches(Drive(),'root')
        self.assertEqual([b['name'] for b in batches],['1.1 Exit Ticket.pdf','1.2 Exit Ticket','1.10 Exit Ticket'])
        self.assertEqual([len(b['files']) for b in batches],[1,2,1])


if __name__ == '__main__': unittest.main()
