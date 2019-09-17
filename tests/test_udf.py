from unittest import TestCase, SkipTest
import tempfile
import pymonetdb
from tests.util import test_args


class TestUdf(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = pymonetdb.connect(**test_args)
        cls.cursor = cls.conn.cursor()

    def test_debug_udf(self):
        self.cursor.execute("""
            CREATE FUNCTION test_python_udf(i INTEGER)
            RETURNS INTEGER
            LANGUAGE PYTHON {
                return i * 2;
            };
            """)
        # test if Python UDFs are enabled on the server
        try:
            self.cursor.execute('SELECT test_python_udf(1);')
        except pymonetdb.exceptions.OperationalError:
            raise SkipTest("We cant assume MonetDB is compiled with embbed python support enabled")

        else:
            result = self.cursor.fetchall()
            self.assertEqual(result, [(2,)])
            # test python debugging capabilities
            with tempfile.NamedTemporaryFile(delete=False) as f:
                fname = f.name
            self.cursor.export('SELECT test_python_udf(1)', 'test_python_udf', filespath=fname)
            fname += "test_python_udf.py"
            with open(fname) as f:
                code = f.read()
                self.assertEqual('test_python_udf(i)' in code, True)
