# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.  If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright 1997 - July 2008 CWI, August 2008 - 2016 MonetDB B.V.

from datetime import datetime, timedelta, timezone
import unittest
import pymonetdb.sql.pythonize
from tests.util import test_args


class TestPythonize(unittest.TestCase):

    def setUp(self):
        db = pymonetdb.connect(autocommit=False, **test_args)
        self.connection = db
        self.cursor = db.cursor()

    def tearDown(self):
        self.connection.close()

    def test_Binary(self):
        input1 = bytes(range(256)).hex()
        output1 = bytes(range(256))
        result1 = pymonetdb.sql.pythonize.Binary(input1)
        self.assertEqual(output1, result1)

        input2 = b'\tdharma'.hex()
        output2 = b'\tdharma'

        result2 = pymonetdb.sql.pythonize.Binary(input2)
        self.assertEqual(output2, result2)

    def test_month_interval(self):
        self.cursor.execute('CREATE TEMPORARY TABLE foo (i INTERVAL MONTH)')
        self.cursor.execute('INSERT INTO foo VALUES (INTERVAL \'2\' YEAR)')
        self.cursor.execute('SELECT * from FOO')
        row = self.cursor.fetchone()
        self.assertEqual(row[0], 24)

    def test_timestamptz(self):
        now = datetime.now()
        self.cursor.execute('SELECT now()')
        row = self.cursor.fetchone()
        ts = row[0]

        # ts is timezone-aware, see the datetime docs
        self.assertIsNotNone(ts.tzinfo)
        self.assertIsNotNone(ts.tzinfo.utcoffset(ts))

        # ts is correct, allowing for reasonable clock skew between client and server
        self.assertAlmostEqual(60 * ts.hour + ts.minute, 60 * now.hour + now.minute, delta=12)

    def test_roundtrip(self):
        dt = datetime(2020, 2, 14, 20, 50)
        tz = timezone(timedelta(hours=1))
        dtz = dt.replace(tzinfo=tz)

        self.cursor.execute('SELECT %s, %s', [dt, dtz])
        row = self.cursor.fetchone()

        self.assertEqual(row[0].isoformat(), dt.isoformat())
        self.assertEqual(row[1].isoformat(), dtz.isoformat())
