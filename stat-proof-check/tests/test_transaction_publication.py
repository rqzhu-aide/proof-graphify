from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_proofcheck import proofcheck


class TransactionPublicationTests(unittest.TestCase):
    def test_report_relocation_rolls_back_after_deletion_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new, manifest = (root / name for name in ('old.html', 'new.html', 'manifest.json'))
            old.write_bytes(b'old report')
            manifest.write_bytes(b'old manifest')
            guard = {p: proofcheck.sha256_file(p) for p in (old, manifest)}
            unlink = Path.unlink
            failed = False

            def unlink_then_fail(path, *args, **kwargs):
                nonlocal failed
                unlink(path, *args, **kwargs)
                if path == old and not failed:
                    failed = True
                    raise OSError('interrupted after old report deletion')

            with mock.patch.object(Path, 'unlink', unlink_then_fail):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    proofcheck.transactional_write_texts(
                        [(new, 'new report'), (manifest, 'new manifest')],
                        expected_sha256=guard, expected_absent=[new], deletes=[old])
            self.assertEqual(b'old report', old.read_bytes())
            self.assertEqual(b'old manifest', manifest.read_bytes())
            self.assertFalse(new.exists())
            self.assertEqual({old, manifest}, set(root.iterdir()))

    def test_new_evidence_appearing_during_publication_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry, ledger = root / 'registry.json', root / 'ledger.json'
            registry.write_bytes(b'old registry')
            publish = proofcheck.publish_no_overwrite

            def race(temporary, destination, description):
                destination.write_bytes(b'concurrent reviewer evidence')
                return publish(temporary, destination, description)

            with mock.patch.object(proofcheck, 'publish_no_overwrite', side_effect=race):
                with self.assertRaises(FileExistsError):
                    proofcheck.transactional_write_texts(
                        [(registry, 'new registry'), (ledger, 'new ledger')],
                        expected_sha256={registry: proofcheck.sha256_file(registry)},
                        expected_absent=[ledger])
            self.assertEqual(b'old registry', registry.read_bytes())
            self.assertEqual(b'concurrent reviewer evidence', ledger.read_bytes())
            self.assertEqual({registry, ledger}, set(root.iterdir()))

    def test_deletion_requires_matching_known_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.html'
            path.write_bytes(b'original')
            for guard in (None, {path: '0' * 64}):
                with self.subTest(guard=guard), self.assertRaises(ValueError):
                    proofcheck.transactional_write_texts([], deletes=[path], expected_sha256=guard)
                self.assertEqual(b'original', path.read_bytes())

    def test_write_and_delete_same_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.html'
            path.write_bytes(b'original')
            with self.assertRaisesRegex(ValueError, 'distinct'):
                proofcheck.transactional_write_texts(
                    [(path, 'new')], deletes=[path],
                    expected_sha256={path: proofcheck.sha256_file(path)})
            self.assertEqual(b'original', path.read_bytes())
            self.assertEqual([path], list(Path(directory).iterdir()))


if __name__ == '__main__':
    unittest.main()
