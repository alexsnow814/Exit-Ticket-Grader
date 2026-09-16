"""Drive folder inventories and lossless, in-memory multi-PDF batches."""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor

PDF_MIME = 'application/pdf'
FOLDER_MIME = 'application/vnd.google-apps.folder'


def list_matching(drive, query: str) -> list[dict]:
    files = []
    token = None
    while True:
        params = {
            'q': query,
            'fields': 'nextPageToken,files(id,name,mimeType,modifiedTime,size,parents)',
            'pageSize': 1000,
            'orderBy': 'name',
        }
        if token:
            params['pageToken'] = token
        response = drive.get('https://www.googleapis.com/drive/v3/files', params=params, timeout=30)
        response.raise_for_status()
        body = response.json()
        files.extend(body.get('files', []))
        token = body.get('nextPageToken')
        if not token:
            return files


def list_children(drive, folder_id: str) -> list[dict]:
    return list_matching(drive, f"'{folder_id}' in parents and trashed = false")


def file_versions(files: list[dict]) -> tuple[tuple[str, str, str], ...]:
    # Stable alphabetical file order, with ID as a tie-breaker. A revision or
    # upload invalidates both the merged document and its processed batch key.
    ordered = sorted(files, key=lambda f: (f['name'].casefold(), f['id']))
    return tuple((f['id'], f.get('modifiedTime', ''), f.get('size', '')) for f in ordered)


def batch_record(item: dict, files: list[dict]) -> dict:
    versions = file_versions(files)
    revision = hashlib.sha256(json.dumps(versions).encode()).hexdigest()[:20]
    return {**item, 'id': f"{item['id']}:{revision}", 'files': versions}


def list_batches(drive, folder_id: str) -> list[dict]:
    batches = []
    inventory = list_children(drive, folder_id)
    folders = [f for f in inventory if f['mimeType'] == FOLDER_MIME]
    # Public folders need individual queries; a small bounded pool keeps each
    # grading rerun quick without caching away newly uploaded PDFs.
    with ThreadPoolExecutor(max_workers=4) as pool:
        contents = list(pool.map(lambda f: list_children(drive, f['id']), folders))
    by_parent = dict(zip((f['id'] for f in folders), contents))
    for item in inventory:
        if item['mimeType'] == FOLDER_MIME:
            # Publicly shared folders must be queried individually: Drive can
            # omit their contents for an OR query spanning multiple parents.
            files = [f for f in by_parent[item['id']] if f['mimeType'] == PDF_MIME]
            if files:
                batches.append(batch_record(item, files))
        elif item['mimeType'] == PDF_MIME:
            # Backward compatibility while older loose PDFs are being moved.
            batches.append(batch_record(item, [item]))
    def sort_key(item):
        match = re.match(r'^(\d+)\.(\d+)\b', item['name'])
        numbers = tuple(map(int, match.groups())) if match else (999999, 999999)
        return (*numbers, item['name'].casefold(), item['id'])
    return sorted(batches, key=sort_key)


def combine_pdfs(documents: list[bytes]) -> bytes:
    import fitz
    if not documents:
        raise ValueError('This exit-ticket folder has no PDF files.')
    if len(documents) == 1:
        return documents[0]
    with fitz.open() as merged:
        for pdf_bytes in documents:
            with fitz.open(stream=pdf_bytes, filetype='pdf') as source:
                merged.insert_pdf(source)
        return merged.tobytes(garbage=3, deflate=True)
