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

import datetime
import sys

from oslo.config import cfg
from oslotest import base as test_base

from openstack.common import importutils


class ImportUtilsTest(test_base.BaseTestCase):

    # NOTE(jkoelker) There has GOT to be a way to test this. But mocking
    #                __import__ is the devil. Right now we just make
    #               sure we can import something from the stdlib
    def test_import_class(self):
        dt = importutils.import_class('datetime.datetime')
        self.assertEqual(sys.modules['datetime'].datetime, dt)

    def test_import_bad_class(self):
        self.assertRaises(ImportError, importutils.import_class,
                          'lol.u_mad.brah')

    def test_import_module(self):
        dt = importutils.import_module('datetime')
        self.assertEqual(sys.modules['datetime'], dt)

    def test_import_object_optional_arg_not_present(self):
        obj = importutils.import_object('tests.unit.fake.FakeDriver')
        self.assertEqual(obj.__class__.__name__, 'FakeDriver')

    def test_import_object_optional_arg_present(self):
        obj = importutils.import_object('tests.unit.fake.FakeDriver',
                                        first_arg=False)
        self.assertEqual(obj.__class__.__name__, 'FakeDriver')

    def test_import_object_required_arg_not_present(self):
        # arg 1 isn't optional here
        self.assertRaises(TypeError, importutils.import_object,
                          'tests.unit.fake.FakeDriver2')

    def test_import_object_required_arg_present(self):
        obj = importutils.import_object('tests.unit.fake.FakeDriver2',
                                        first_arg=False)
        self.assertEqual(obj.__class__.__name__, 'FakeDriver2')

    # namespace tests
    def test_import_object_ns_optional_arg_not_present(self):
        obj = importutils.import_object_ns('tests.unit', 'fake.FakeDriver')
        self.assertEqual(obj.__class__.__name__, 'FakeDriver')

    def test_import_object_ns_optional_arg_present(self):
        obj = importutils.import_object_ns('tests.unit', 'fake.FakeDriver',
                                           first_arg=False)
        self.assertEqual(obj.__class__.__name__, 'FakeDriver')

    def test_import_object_ns_required_arg_not_present(self):
        # arg 1 isn't optional here
        self.assertRaises(TypeError, importutils.import_object_ns,
                          'tests.unit', 'fake.FakeDriver2')

    def test_import_object_ns_required_arg_present(self):
        obj = importutils.import_object_ns('tests.unit', 'fake.FakeDriver2',
                                           first_arg=False)
        self.assertEqual(obj.__class__.__name__, 'FakeDriver2')

    # namespace tests
    def test_import_object_ns_full_optional_arg_not_present(self):
        obj = importutils.import_object_ns('tests.unit2',
                                           'tests.unit.fake.FakeDriver')
        self.assertEqual(obj.__class__.__name__, 'FakeDriver')

    def test_import_object_ns_full_optional_arg_present(self):
        obj = importutils.import_object_ns('tests.unit2',
                                           'tests.unit.fake.FakeDriver',
                                           first_arg=False)
        self.assertEqual(obj.__class__.__name__, 'FakeDriver')

    def test_import_object_ns_full_required_arg_not_present(self):
        # arg 1 isn't optional here
        self.assertRaises(TypeError, importutils.import_object_ns,
                          'tests.unit2', 'tests.unit.fake.FakeDriver2')

    def test_import_object_ns_full_required_arg_present(self):
        obj = importutils.import_object_ns('tests.unit2',
                                           'tests.unit.fake.FakeDriver2',
                                           first_arg=False)
        self.assertEqual(obj.__class__.__name__, 'FakeDriver2')

    def test_import_object(self):
        dt = importutils.import_object('datetime.time')
        self.assertTrue(isinstance(dt, sys.modules['datetime'].time))

    def test_import_object_with_args(self):
        dt = importutils.import_object('datetime.datetime', 2012, 4, 5)
        self.assertTrue(isinstance(dt, sys.modules['datetime'].datetime))
        self.assertEqual(dt, datetime.datetime(2012, 4, 5))

    def test_try_import(self):
        dt = importutils.try_import('datetime')
        self.assertEqual(sys.modules['datetime'], dt)

    def test_try_import_returns_default(self):
        foo = importutils.try_import('foo.bar')
        self.assertIsNone(foo)

    def test_load_lazy_pluggable_without_config_group(self):
        conf = cfg.ConfigOpts()
        test_backend = cfg.StrOpt('foo',
                                  default='bar',
                                  help='This module will be imported lazily')
        conf.register_opt(test_backend)
        module_name = 'tests.unit.test_importutils'
        from_list = 'tests.unit.test_importutils'
        _backend = importutils.LazyPluggable(conf, 'foo', config_group=None,
                                             bar=module_name)

        self.assertIs(__import__(module_name, None, None, from_list),
                      _backend._get_backend())

    def test_load_lazy_pluggable_with_config_group(self):
        conf = cfg.ConfigOpts()
        test_backend = cfg.StrOpt('foo',
                                  default='bar',
                                  help='This module will be imported lazily')
        test_group = cfg.OptGroup(name='group', title='Test Options')
        conf.register_group(test_group)
        conf.register_opt(test_backend, test_group)
        module_name = 'tests.unit.test_importutils'
        from_list = 'tests.unit.test_importutils'
        _backend = importutils.LazyPluggable(conf, 'foo', config_group='group',
                                             bar=module_name)

        self.assertIs(__import__(module_name, None, None, from_list),
                      _backend._get_backend())

    def test_load_lazy_pluggable_when_backend_is_tuple(self):
        conf = cfg.ConfigOpts()
        test_backend = cfg.StrOpt('foo',
                                  default='bar',
                                  help='This module will be imported lazily')
        conf.register_opt(test_backend)
        module_name = 'tests.unit.test_importutils'
        from_list = 'tests.unit.test_importutils'
        _backend = importutils.LazyPluggable(conf, 'foo', config_group=None,
                                             bar=(module_name, from_list))

        self.assertIs(__import__(module_name, None, None, from_list),
                      _backend._get_backend())

    def test_load_lazy_pluggable_when_backend_tuple_length_is_incorrect(self):
        conf = cfg.ConfigOpts()
        test_backend = cfg.StrOpt('foo',
                                  default='bar',
                                  help='This module will be imported lazily')
        conf.register_opt(test_backend)
        module_name = 'tests.unit.test_importutils'
        _backend = importutils.LazyPluggable(conf, 'foo', config_group=None,
                                             bar=tuple(module_name))

        self.assertRaises(ValueError, _backend._get_backend)

    def test_load_lazy_pluggable_raise_of_PluginLoadError(self):
        conf = cfg.ConfigOpts()
        test_backend = cfg.StrOpt('foo',
                                  default='bar_1',
                                  help='This module will be imported lazily')
        conf.register_opt(test_backend)
        module_name = 'tests.unit.test_importutils'
        _backend = importutils.LazyPluggable(conf, 'foo', config_group=None,
                                             bar_2=module_name)

        self.assertRaises(importutils.PluginLoadError, _backend._get_backend)

    def test_verify_lazyness_itself(self):
        conf = cfg.ConfigOpts()
        test_backend = cfg.StrOpt('foo',
                                  default='bar',
                                  help='This module will be imported lazily')
        conf.register_opt(test_backend)
        module_name = 'tests.unit.test_importutils'
        _backend = importutils.LazyPluggable(conf, 'foo', config_group=None,
                                             bar=module_name)

        self.assertEqual(None, _backend._backend)
