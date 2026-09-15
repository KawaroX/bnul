import io
import unittest
from importlib.metadata import version
from unittest.mock import patch
from bnul.cli import main


class VersionTests(unittest.TestCase):
    def test_version_exits_without_client(self):
        for flag in ('-v', '--version'):
            with patch('bnul.cli.Client') as client, patch('sys.stdout', new_callable=io.StringIO) as out:
                with self.assertRaises(SystemExit) as result:
                    main([flag])
                self.assertEqual(result.exception.code, 0)
                self.assertEqual(out.getvalue(), f'bnul {version("bnul")}\n')
                client.assert_not_called()
