# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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

"""
Unit Tests for rpc.proxy
"""

import copy

from openstack.common import context
from openstack.common import lockutils
from openstack.common.fixture import moxstubout
from openstack.common import rpc
from openstack.common.rpc import proxy
from openstack.common.rpc import common as rpc_common
from tests import utils


class RpcProxyTestCase(utils.BaseTestCase):

    def _test_rpc_method(self, rpc_method, has_timeout=False, has_retval=False,
                         server_params=None, supports_topic_override=True):
        topic = 'fake_topic'
        timeout = 123
        rpc_proxy = proxy.RpcProxy(topic, '1.0')
        ctxt = context.RequestContext('fake_user', 'fake_project')
        msg = {'method': 'fake_method', 'args': {'x': 'y'}}
        expected_msg = {'method': 'fake_method', 'args': {'x': 'y'},
                        'version': '1.0'}

        expected_retval = 'hi' if has_retval else None

        self.fake_args = None
        self.fake_kwargs = None

        def _fake_rpc_method(*args, **kwargs):
            rpc._check_for_lock()
            self.fake_args = args
            self.fake_kwargs = kwargs
            if has_retval:
                return expected_retval

        def _fake_rpc_method_timeout(*args, **kwargs):
            rpc._check_for_lock()
            self.fake_args = args
            self.fake_kwargs = kwargs
            raise rpc_common.Timeout("The spider got you")

        def _check_args(timeout=None):
            if server_params:
                expected_args.insert(1, server_params)
            if has_timeout:
                expected_args.append(timeout)
            if len(self.fake_args) != len(expected_args):
                self.assertEqual(expected_args, self.fake_args)
            for arg, expected_arg in zip(self.fake_args, expected_args):
                self.assertEqual(arg, expected_arg)

        self.stubs.Set(rpc, rpc_method, _fake_rpc_method)

        args = [ctxt, msg]
        if server_params:
            args.insert(1, server_params)

        # Base method usage
        retval = getattr(rpc_proxy, rpc_method)(*args)
        self.assertEqual(retval, expected_retval)
        expected_args = [ctxt, topic, expected_msg]
        _check_args()

        # overriding the version
        retval = getattr(rpc_proxy, rpc_method)(*args, version='1.1')
        self.assertEqual(retval, expected_retval)
        new_msg = copy.deepcopy(expected_msg)
        new_msg['version'] = '1.1'
        expected_args = [ctxt, topic, new_msg]
        _check_args()

        if has_timeout:
            # Set a timeout
            retval = getattr(rpc_proxy, rpc_method)(ctxt, msg, timeout=timeout)
            self.assertEqual(retval, expected_retval)
            expected_args = [ctxt, topic, expected_msg]
            _check_args(timeout)

            # Make it timeout and check that the exception is written as
            # expected
            self.stubs.Set(rpc, rpc_method, _fake_rpc_method_timeout)
            try:
                getattr(rpc_proxy, rpc_method)(*args, timeout=timeout)
                self.fail("This should have raised a Timeout exception")
            except rpc_common.Timeout as exc:
                self.assertEqual(
                    'The spider got you - '
                    'Topic: "fake_topic" - RPC Method: "fake_method"',
                    str(exc))
            expected_args = [ctxt, topic, expected_msg]
            _check_args(timeout)
            self.stubs.Set(rpc, rpc_method, _fake_rpc_method)

        if supports_topic_override:
            # set a topic
            new_topic = 'foo.bar'
            retval = getattr(rpc_proxy, rpc_method)(*args, topic=new_topic)
            self.assertEqual(retval, expected_retval)
            expected_args = [ctxt, new_topic, expected_msg]
            _check_args()

    def test_call(self):
        self._test_rpc_method('call', has_timeout=True, has_retval=True)

    def test_multicall(self):
        self._test_rpc_method('multicall', has_timeout=True, has_retval=True)

    def test_multicall_with_lock_held(self):
        self.config(debug=True)
        self.assertFalse(rpc._check_for_lock())

        @lockutils.synchronized('detecting', 'test-')
        def f():
            self.assertTrue(rpc._check_for_lock())
        f()

        self.assertFalse(rpc._check_for_lock())

    def test_cast(self):
        self._test_rpc_method('cast')

    def test_fanout_cast(self):
        self._test_rpc_method('fanout_cast', supports_topic_override=False)

    def test_cast_to_server(self):
        self._test_rpc_method('cast_to_server', server_params={'blah': 1})

    def test_fanout_cast_to_server(self):
        self._test_rpc_method(
            'fanout_cast_to_server',
            server_params={'blah': 1}, supports_topic_override=False)

    def test_make_msg(self):
        self.assertEqual(proxy.RpcProxy.make_msg('test_method', a=1, b=2),
                         {'method': 'test_method', 'args': {'a': 1, 'b': 2}})
