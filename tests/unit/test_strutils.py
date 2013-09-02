# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock
import six

from openstack.common import strutils
from openstack.common import test


class StrUtilsTest(test.BaseTestCase):

    def test_bool_bool_from_string(self):
        self.assertTrue(strutils.bool_from_string(True))
        self.assertFalse(strutils.bool_from_string(False))

    def _test_bool_from_string(self, c):
        self.assertTrue(strutils.bool_from_string(c('true')))
        self.assertTrue(strutils.bool_from_string(c('TRUE')))
        self.assertTrue(strutils.bool_from_string(c('on')))
        self.assertTrue(strutils.bool_from_string(c('On')))
        self.assertTrue(strutils.bool_from_string(c('yes')))
        self.assertTrue(strutils.bool_from_string(c('YES')))
        self.assertTrue(strutils.bool_from_string(c('yEs')))
        self.assertTrue(strutils.bool_from_string(c('1')))
        self.assertTrue(strutils.bool_from_string(c('T')))
        self.assertTrue(strutils.bool_from_string(c('t')))
        self.assertTrue(strutils.bool_from_string(c('Y')))
        self.assertTrue(strutils.bool_from_string(c('y')))

        self.assertFalse(strutils.bool_from_string(c('false')))
        self.assertFalse(strutils.bool_from_string(c('FALSE')))
        self.assertFalse(strutils.bool_from_string(c('off')))
        self.assertFalse(strutils.bool_from_string(c('OFF')))
        self.assertFalse(strutils.bool_from_string(c('no')))
        self.assertFalse(strutils.bool_from_string(c('0')))
        self.assertFalse(strutils.bool_from_string(c('42')))
        self.assertFalse(strutils.bool_from_string(c(
                         'This should not be True')))
        self.assertFalse(strutils.bool_from_string(c('F')))
        self.assertFalse(strutils.bool_from_string(c('f')))
        self.assertFalse(strutils.bool_from_string(c('N')))
        self.assertFalse(strutils.bool_from_string(c('n')))

        # Whitespace should be stripped
        self.assertTrue(strutils.bool_from_string(c(' 1 ')))
        self.assertTrue(strutils.bool_from_string(c(' true ')))
        self.assertFalse(strutils.bool_from_string(c(' 0 ')))
        self.assertFalse(strutils.bool_from_string(c(' false ')))

    def test_bool_from_string(self):
        self._test_bool_from_string(lambda s: s)

    def test_unicode_bool_from_string(self):
        self._test_bool_from_string(six.text_type)
        self.assertFalse(strutils.bool_from_string(u'使用', strict=False))

        exc = self.assertRaises(ValueError, strutils.bool_from_string,
                                u'使用', strict=True)
        expected_msg = (u"Unrecognized value '使用', acceptable values are:"
                        u" '0', '1', 'f', 'false', 'n', 'no', 'off', 'on',"
                        u" 't', 'true', 'y', 'yes'")
        self.assertEqual(expected_msg, unicode(exc))

    def test_other_bool_from_string(self):
        self.assertFalse(strutils.bool_from_string(None))
        self.assertFalse(strutils.bool_from_string(mock.Mock()))

    def test_int_bool_from_string(self):
        self.assertTrue(strutils.bool_from_string(1))

        self.assertFalse(strutils.bool_from_string(-1))
        self.assertFalse(strutils.bool_from_string(0))
        self.assertFalse(strutils.bool_from_string(2))

    def test_strict_bool_from_string(self):
        # None isn't allowed in strict mode
        exc = self.assertRaises(ValueError, strutils.bool_from_string, None,
                                strict=True)
        expected_msg = ("Unrecognized value 'None', acceptable values are:"
                        " '0', '1', 'f', 'false', 'n', 'no', 'off', 'on',"
                        " 't', 'true', 'y', 'yes'")
        self.assertEqual(expected_msg, str(exc))

        # Unrecognized strings aren't allowed
        self.assertFalse(strutils.bool_from_string('Other', strict=False))
        exc = self.assertRaises(ValueError, strutils.bool_from_string, 'Other',
                                strict=True)
        expected_msg = ("Unrecognized value 'Other', acceptable values are:"
                        " '0', '1', 'f', 'false', 'n', 'no', 'off', 'on',"
                        " 't', 'true', 'y', 'yes'")
        self.assertEqual(expected_msg, str(exc))

        # Unrecognized numbers aren't allowed
        exc = self.assertRaises(ValueError, strutils.bool_from_string, 2,
                                strict=True)
        expected_msg = ("Unrecognized value '2', acceptable values are:"
                        " '0', '1', 'f', 'false', 'n', 'no', 'off', 'on',"
                        " 't', 'true', 'y', 'yes'")
        self.assertEqual(expected_msg, str(exc))

        # False-like values are allowed
        self.assertFalse(strutils.bool_from_string('f', strict=True))
        self.assertFalse(strutils.bool_from_string('false', strict=True))
        self.assertFalse(strutils.bool_from_string('off', strict=True))
        self.assertFalse(strutils.bool_from_string('n', strict=True))
        self.assertFalse(strutils.bool_from_string('no', strict=True))
        self.assertFalse(strutils.bool_from_string('0', strict=True))

        self.assertTrue(strutils.bool_from_string('1', strict=True))

        # Avoid font-similarity issues (one looks like lowercase-el, zero like
        # oh, etc...)
        for char in ('O', 'o', 'L', 'l', 'I', 'i'):
            self.assertRaises(ValueError, strutils.bool_from_string, char,
                              strict=True)

    def test_int_from_bool_as_string(self):
        self.assertEqual(1, strutils.int_from_bool_as_string(True))
        self.assertEqual(0, strutils.int_from_bool_as_string(False))

    def test_safe_decode(self):
        safe_decode = strutils.safe_decode
        self.assertRaises(TypeError, safe_decode, True)
        self.assertEqual(six.u('ni\xf1o'), safe_decode("ni\xc3\xb1o",
                         incoming="utf-8"))
        self.assertEqual(six.u("test"), safe_decode("dGVzdA==",
                         incoming='base64'))

        self.assertEqual(six.u("strange"), safe_decode('\x80strange',
                         errors='ignore'))

        self.assertEqual(six.u('\xc0'), safe_decode('\xc0',
                         incoming='iso-8859-1'))

        # Forcing incoming to ascii so it falls back to utf-8
        self.assertEqual(six.u('ni\xf1o'), safe_decode('ni\xc3\xb1o',
                         incoming='ascii'))

    def test_safe_encode(self):
        safe_encode = strutils.safe_encode
        self.assertRaises(TypeError, safe_encode, True)
        self.assertEqual("ni\xc3\xb1o", safe_encode(six.u('ni\xf1o'),
                                                    encoding="utf-8"))
        self.assertEqual("dGVzdA==\n", safe_encode("test",
                                                   encoding='base64'))
        self.assertEqual('ni\xf1o', safe_encode("ni\xc3\xb1o",
                                                encoding="iso-8859-1",
                                                incoming="utf-8"))

        # Forcing incoming to ascii so it falls back to utf-8
        self.assertEqual('ni\xc3\xb1o', safe_encode('ni\xc3\xb1o',
                                                    incoming='ascii'))

    def test_string_conversions(self):
        working_examples = {
            '1024KB': 1048576,
            '1024TB': 1125899906842624,
            '1024K': 1048576,
            '1024T': 1125899906842624,
            '1TB': 1099511627776,
            '1T': 1099511627776,
            '1KB': 1024,
            '1K': 1024,
            '1B': 1,
            '1': 1,
            '1MB': 1048576,
            '7MB': 7340032,
            '0MB': 0,
            '0KB': 0,
            '0TB': 0,
            '': 0,
        }
        for (in_value, expected_value) in working_examples.items():
            b_value = strutils.to_bytes(in_value)
            self.assertEqual(expected_value, b_value)
            if in_value:
                in_value = "-" + in_value
                b_value = strutils.to_bytes(in_value)
                self.assertEqual(expected_value * -1, b_value)
        breaking_examples = [
            'junk1KB', '1023BBBB',
        ]
        for v in breaking_examples:
            self.assertRaises(TypeError, strutils.to_bytes, v)

    def test_slugify(self):
        to_slug = strutils.to_slug
        self.assertRaises(TypeError, to_slug, True)
        self.assertEqual(six.u("hello"), to_slug("hello"))
        self.assertEqual(six.u("two-words"), to_slug("Two Words"))
        self.assertEqual(six.u("ma-any-spa-ce-es"),
                         to_slug("Ma-any\t spa--ce- es"))
        self.assertEqual(six.u("excamation"), to_slug("exc!amation!"))
        self.assertEqual(six.u("ampserand"), to_slug("&ampser$and"))
        self.assertEqual(six.u("ju5tnum8er"), to_slug("ju5tnum8er"))
        self.assertEqual(six.u("strip-"), to_slug(" strip - "))
        self.assertEqual(six.u("perche"), to_slug("perch\xc3\xa9"))
        self.assertEqual(six.u("strange"),
                         to_slug("\x80strange", errors="ignore"))


class StringToBytesTest(test.BaseTestCase):

    def test_b(self):
        iec_val = strutils.string_to_bytes('79b')
        iec_bit_val = strutils.string_to_bytes('79bit')
        si_val = strutils.string_to_bytes('79b', 'SI')
        expect = 9.875
        self.assertTrue(expect == iec_val == iec_bit_val == si_val)

    def test_B(self):
        iec_val = strutils.string_to_bytes('79B')
        iec_no_unit_val = strutils.string_to_bytes('79')
        si_val = strutils.string_to_bytes('79B', 'SI')
        si_no_unit_val = strutils.string_to_bytes('79', 'SI')
        expect = 79.0
        self.assertTrue(expect == iec_val == iec_no_unit_val ==
                        si_val == si_no_unit_val)

    def test_iec_kb(self):
        self.assertRaises(TypeError, strutils.string_to_bytes, '79kb')
        self.assertRaises(TypeError, strutils.string_to_bytes, '79kbit')
        self.assertRaises(TypeError, strutils.string_to_bytes, '79kib')
        self.assertRaises(TypeError, strutils.string_to_bytes, '79kibit')

    def test_iec_kB(self):
        self.assertRaises(TypeError, strutils.string_to_bytes, '79kB')
        self.assertRaises(TypeError, strutils.string_to_bytes, '79kiB')

    def test_iec_Kb(self):
        iec_kb_val = strutils.string_to_bytes('79Kb')
        iec_kib_val = strutils.string_to_bytes('79Kib')
        iec_kibit_val = strutils.string_to_bytes('79Kibit')
        expect = 79.0 / 8 * 1024
        self.assertTrue(expect == iec_kb_val == iec_kib_val == iec_kibit_val)

    def test_iec_KB(self):
        iec_kb_val = strutils.string_to_bytes('79KB')
        iec_kib_val = strutils.string_to_bytes('79KiB')
        expect = 79.0 * 1024
        self.assertTrue(expect == iec_kb_val == iec_kib_val)

    def test_iec_Mb(self):
        iec_mb_val = strutils.string_to_bytes('79Mb')
        iec_mib_val = strutils.string_to_bytes('79Mib')
        iec_mibit_val = strutils.string_to_bytes('79Mibit')
        expect = 79.0 / 8 * pow(1024, 2)
        self.assertTrue(expect == iec_mb_val == iec_mib_val == iec_mibit_val)

    def test_iec_MB(self):
        iec_mb_val = strutils.string_to_bytes('79MB')
        iec_mib_val = strutils.string_to_bytes('79MiB')
        expect = 79.0 * pow(1024, 2)
        self.assertTrue(expect == iec_mb_val == iec_mib_val)

    def test_iec_Gb(self):
        iec_gb_val = strutils.string_to_bytes('79Gb')
        iec_gib_val = strutils.string_to_bytes('79Gib')
        iec_gibit_val = strutils.string_to_bytes('79Gibit')
        expect = 79.0 / 8 * pow(1024, 3)
        self.assertTrue(expect == iec_gb_val == iec_gib_val == iec_gibit_val)

    def test_iec_GB(self):
        iec_gb_val = strutils.string_to_bytes('79GB')
        iec_gib_val = strutils.string_to_bytes('79GiB')
        expect = 79.0 * pow(1024, 3)
        self.assertTrue(expect == iec_gb_val == iec_gib_val)

    def test_iec_Tb(self):
        iec_tb_val = strutils.string_to_bytes('79Tb')
        iec_tib_val = strutils.string_to_bytes('79Tib')
        iec_tibit_val = strutils.string_to_bytes('79Tibit')
        expect = 79.0 / 8 * pow(1024, 4)
        self.assertTrue(expect == iec_tb_val == iec_tib_val == iec_tibit_val)

    def test_iec_TB(self):
        iec_tb_val = strutils.string_to_bytes('79TB')
        iec_tib_val = strutils.string_to_bytes('79TiB')
        expect = 79.0 * pow(1024, 4)
        self.assertTrue(expect == iec_tb_val == iec_tib_val)

    def test_si_kb(self):
        iec_kb_val = strutils.string_to_bytes('79kb', unit_system='SI')
        expect = 79.0 / 8 * 1000
        self.assertEqual(expect, iec_kb_val)

    def test_si_kB(self):
        iec_kb_val = strutils.string_to_bytes('79kB', unit_system='SI')
        expect = 79.0 * 1000
        self.assertEqual(expect, iec_kb_val)

    def test_si_Kb(self):
        self.assertRaises(TypeError, strutils.string_to_bytes,
                          '79Kb', unit_system='SI')

    def test_si_KB(self):
        self.assertRaises(TypeError, strutils.string_to_bytes,
                          '79KB', unit_system='SI')

    def test_si_Mb(self):
        pass

    def test_si_MB(self):
        pass

    def test_si_Gb(self):
        pass

    def test_si_GB(self):
        pass

    def test_si_Tb(self):
        pass

    def test_si_TB(self):
        pass
