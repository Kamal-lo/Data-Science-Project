"""Entrées malveillantes miniatures et budgets bas, sans bombe ZIP volumineuse."""
from dataclasses import replace
import io
import stat
import struct
import zipfile

from ingestion_fixtures import IngestionCase, docx_bytes, pdf_bytes, zip_bytes
from P2_nlp_extraction.document_ingestion.models import Budget, IngestionFailure, IngestionLimits


class SecurityTests(IngestionCase):
    def test_traversal_absolute_ads_reserved_and_control_names(self):
        for name in ('../escape.pdf', '..\\escape.pdf', '/root/file', 'C:\\file.pdf',
                     'C:relative', '\\\\server\\share\\file', 'a/../b', 'NUL.pdf',
                     'COM1.txt', 'a./file', 'a /file', 'a:stream', 'a//b', 'a\x01b', 'a\x00evil'):
            with self.subTest(name=repr(name)):
                # ZipInfo conserve orig_filename ; le writer tronque NUL, testé directement ci-dessous.
                if '\x00' in name:
                    from P2_nlp_extraction.document_ingestion.safety import validate_entries
                    info = zipfile.ZipInfo(name)
                    with self.assertRaises(IngestionFailure):
                        validate_entries([info], IngestionLimits())
                else:
                    self.assert_rejected(self.direct(zip_bytes([(name, b'x')])),'unsafe_path')
        self.assertFalse((self.folder.parent/'escape.pdf').exists())

    def test_symlink_and_special_entries(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            info = zipfile.ZipInfo('special'); info.create_system = 3
            info.external_attr = (mode | 0o777) << 16
            self.assert_rejected(self.direct(zip_bytes([(info, b'target')])),'special_entry')

    def test_case_unicode_duplicate_and_file_directory_collisions(self):
        for names in (('A.pdf','a.pdf'), ('é.pdf','e\u0301.pdf'), ('a','a/b'),
                      ('a/b','a'), ('A/x','a/y'), ('a','a')):
            with self.subTest(names=names):
                self.assert_rejected(self.direct(zip_bytes([(name,b'x') for name in names])),'path_collision')

    def test_path_depth_and_length(self):
        self.assert_rejected(self.direct(zip_bytes([('a/b/c',b'x')]), max_depth=2),'path_limit')
        self.assert_rejected(self.direct(zip_bytes([('long_name',b'x')]), max_path_chars=3),'path_limit')

    def test_entry_metadata_and_file_size_limits(self):
        self.assert_rejected(self.direct(zip_bytes([('a',b'x'),('b',b'x')]), max_entries=1),'entry_count_limit')
        self.assert_rejected(self.direct(zip_bytes([('a',b'x')]), max_metadata_bytes=10),'metadata_limit')
        self.assert_rejected(self.direct(zip_bytes([('a',b'x')]), max_file_bytes=10),'file_size_limit')

    def test_total_budget_counts_actual_reads(self):
        data = pdf_bytes(); archive = zip_bytes([('ok.pdf',data)])
        self.assert_rejected(self.direct(archive, max_total_bytes=len(archive)+len(data)-1),'total_size_limit')

    def test_small_high_ratio_archive(self):
        data = zip_bytes([('small.txt',b'A'*4000)], compression=zipfile.ZIP_DEFLATED)
        self.assert_rejected(self.direct(data, max_compression_ratio=2),'compression_ratio_limit')

    def test_nested_zip_is_not_expanded_but_docx_is_accepted(self):
        inner = zip_bytes([('hidden.pdf',pdf_bytes())])
        result = self.direct(zip_bytes([('nested.dat',inner),('normal.docx',docx_bytes())]))
        self.assertEqual(result['status'], 'completed_with_issues')
        nested, word = result['files']
        self.assertEqual(nested['reason'], 'nested_archive_not_allowed')
        self.assertFalse(nested['eligible_for_t24'])
        self.assertTrue(word['eligible_for_t24'])
        self.assertFalse((self.last_run/'files/hidden.pdf').exists())

    def test_corruption_revokes_already_inspected_pdf(self):
        data = bytearray(zip_bytes([('good.pdf',pdf_bytes()),('bad.bin',b'PAYLOAD')]))
        data[data.index(b'PAYLOAD')] ^= 1
        result = self.direct(bytes(data))
        self.assert_rejected(result, 'corrupt_zip')
        self.assertEqual(len(result['files']),1)
        self.assertFalse((self.last_run/'files').exists())

    def test_truncated_archive(self):
        self.assert_rejected(self.direct(zip_bytes([('a',b'x')])[:-8]),'corrupt_zip')

    def test_self_extracting_prefixed_and_pdf_zip_polyglot_refused(self):
        normal=zip_bytes([('a',b'x')])
        self.assert_rejected(self.direct(b'MZprefix'+normal,'disguised.bin'),'zip_layout_unsupported')
        self.assert_rejected(self.direct(b'%PDF-1.7\n'+normal,'polyglot.pdf'),'ambiguous_container')

    def test_central_count_mismatch_and_local_header_conflict(self):
        data=bytearray(zip_bytes([('a',b'x')]))
        struct.pack_into('<H',data,len(data)-22+8,2)
        struct.pack_into('<H',data,len(data)-22+10,2)
        self.assert_rejected(self.direct(bytes(data)),'corrupt_zip')
        data=bytearray(zip_bytes([('a',b'x')]))
        data[30]=ord('b')
        self.assert_rejected(self.direct(bytes(data)),'corrupt_zip')

    def test_encrypted_flag_is_rejected(self):
        data = bytearray(zip_bytes([('a',b'x')]))
        struct.pack_into('<H',data,6,1)
        offset=data.index(b'PK\x01\x02');struct.pack_into('<H',data,offset+8,1)
        self.assert_rejected(self.direct(bytes(data)),'encrypted_zip_unsupported')

    def test_compression_zip64_and_multidisk_rejected(self):
        self.assert_rejected(self.direct(zip_bytes([('a',b'x')],zipfile.ZIP_BZIP2)),'compression_unsupported')
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            with z.open('a','w',force_zip64=True) as f:f.write(b'x')
        self.assert_rejected(self.direct(buffer.getvalue()),'zip64_unsupported')
        data=bytearray(zip_bytes([('a',b'x')]))
        struct.pack_into('<H',data,len(data)-22+4,1)
        self.assert_rejected(self.direct(bytes(data)),'multidisk_unsupported')

    def test_lied_expanded_size_detected_even_with_matching_prefix_crc(self):
        import zlib
        data=bytearray(zip_bytes([('a',b'A'*100)],zipfile.ZIP_DEFLATED))
        central=data.index(b'PK\x01\x02')
        struct.pack_into('<I',data,22,1);struct.pack_into('<I',data,central+24,1)
        crc=zlib.crc32(b'A')
        struct.pack_into('<I',data,14,crc);struct.pack_into('<I',data,central+16,crc)
        self.assert_rejected(self.direct(bytes(data)),'corrupt_zip')

    def test_dtd_entities_xml_size_and_complexity(self):
        main='<!DOCTYPE x [<!ENTITY a "unsafe">]><x>&a;</x>'
        self.assert_rejected(self.direct(docx_bytes(main=main),'unsafe.docx'),'unsafe_xml')
        utf16=('<?xml version="1.0" encoding="utf-16"?>'+main).encode('utf-16')
        self.assert_rejected(self.direct(docx_bytes(main=utf16),'utf16.docx'),'unsafe_xml')
        self.assert_rejected(self.direct(docx_bytes(),'size.docx',max_xml_bytes=20),'xml_size_limit')
        self.assert_rejected(self.direct(docx_bytes(),'complex.docx',max_xml_nodes=1),'xml_complexity_limit')

    def test_monotonic_budget_timeout(self):
        clock=iter([0,2])
        budget=Budget(IngestionLimits(timeout_seconds=1),clock=lambda:next(clock))
        with self.assertRaises(IngestionFailure) as ctx:budget.tick()
        self.assertEqual(ctx.exception.code,'timeout')

    def test_deflate_streams_zero_small_large_and_corrupt_end(self):
        import random
        rng = random.Random(23)
        for size in (0, 1, 64, 4096, 70_000):
            payload = rng.randbytes(size)
            result = self.direct(zip_bytes([('payload.bin', payload)], zipfile.ZIP_DEFLATED))
            self.assertEqual(result['status'], 'completed_with_issues')
            self.assertEqual((self.last_run/'files/payload.bin').read_bytes(), payload)
        # Flux deflate valide suivi d'un octet caché, avec tailles ZIP cohérentes.
        data = bytearray(zip_bytes([('payload.bin', b'ABC')], zipfile.ZIP_DEFLATED))
        old_cd = data.index(b'PK\x01\x02')
        compressed = struct.unpack_from('<I', data, 18)[0]
        data[old_cd:old_cd] = b'X'
        struct.pack_into('<I', data, 18, compressed+1)
        struct.pack_into('<I', data, old_cd+1+20, compressed+1)
        struct.pack_into('<I', data, len(data)-22+16, old_cd+1)
        self.assert_rejected(self.direct(bytes(data)), 'corrupt_zip')
