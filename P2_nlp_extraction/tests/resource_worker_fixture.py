"""Subprocess fixture: synthetic OCR only; never initializes Paddle models."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from P2_nlp_extraction.ocr_pipeline.resources import join_job
from P2_nlp_extraction.ocr_pipeline.worker import process_document
from P2_nlp_extraction.scripts.ocr_common import write_json


def memory_probe(limit, folder):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
    kernel.VirtualAlloc.restype = ctypes.c_void_p
    address = kernel.VirtualAlloc(None, limit * 2, 0x3000, 4)
    write_json(folder/'allocation.json', {'denied': not bool(address), 'windows_error': ctypes.get_last_error()})
    if address:
        kernel.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
        kernel.VirtualFree(address, 0, 0x8000)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--memory-probe':
        memory_probe(int(sys.argv[2]), Path(sys.argv[3]))
        return
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding='utf-8'))
    join_job(request['resource_job_name'])
    folder = Path(request['run_dir'])
    scenario = os.environ.get('P2_TEST_RESOURCE_SCENARIO', 'normal')
    if scenario == 'first_page_blocked':
        scenario = 'blocked' if request['pages'][0] == 1 else 'normal'

    class Models:
        metadata = {'synthetic': True, 'downloads': False}
        initialization_seconds = 0

        def __init__(self, **kwargs):
            self.calls = 0
            write_json(folder/'fixture_process.json', {'pid': os.getpid(), 'synthetic': True})

        def detect(self, image):
            return ([[[10, 10], [200, 10], [200, 40], [10, 40]]], [.9])

        def crop(self, image, polygon): return image[10:40, 10:200].copy()

        def recognize(self, image, language):
            self.calls += 1
            if self.calls > 2:
                if scenario == 'memory':
                    memory_probe(request['max_worker_memory_bytes'], folder)
                if scenario == 'child_memory':
                    child = subprocess.Popen([sys.executable, '-B', '-m',
                        'P2_nlp_extraction.tests.resource_worker_fixture', '--memory-probe',
                        str(request['max_worker_memory_bytes']), str(folder)])
                    write_json(folder/'fixture_child.json', {'pid': child.pid})
                if scenario == 'descendant':
                    child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(60)'])
                    write_json(folder/'fixture_child.json', {'pid': child.pid})
                if scenario in ('blocked', 'memory', 'descendant', 'child_memory'):
                    while True: time.sleep(.01)
            return {'text': ('weak primary' if self.calls <= 2 else 'recovered text') if language == 'fr' else '',
                    'confidence': (.2 if self.calls <= 2 else .98) if language == 'fr' else .1}

    process_document(request, backend_factory=Models)


if __name__ == '__main__': main()
