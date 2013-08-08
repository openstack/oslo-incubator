# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 eNovance
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
import webob

from tests import utils

from openstack.common.middleware import notifier
from openstack.common.notifier import api


class FakeApp(object):
    def __call__(self, env, start_response):
        body = 'Some response'
        start_response('200 OK', [
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(sum(map(len, body))))
        ])
        return [body]


class FakeFailingApp(object):
    def __call__(self, env, start_response):
        raise Exception("It happens!")


class NotifierMiddlewareTest(utils.BaseTestCase):

    def test_notification(self):
        middleware = notifier.RequestNotifier(FakeApp())
        req = webob.Request.blank('/foo/bar',
                                  environ={'REQUEST_METHOD': 'GET'})
        with mock.patch('openstack.common.notifier.api.notify') as notify:
            middleware(req)
            call_args = notify.call_args_list[0][0]
            self.assertEqual(call_args[2], 'http.request')
            self.assertEqual(call_args[3], api.INFO)
            self.assertEqual(set(call_args[4].keys()),
                             set(['request', 'response']))

            request = call_args[4]['request']
            self.assertEqual(request['PATH_INFO'], '/foo/bar')
            self.assertEqual(request['REQUEST_METHOD'], 'GET')
            self.assertFalse(any(map(lambda s: s.startswith('wsgi.'),
                                     request.keys())),
                             "WSGI fields are filtered out")

            response = call_args[4]['response']
            self.assertEqual(response['status'], '200 OK')
            self.assertEqual(response['headers']['content-length'], '13')

    def test_notification_response_failure(self):
        middleware = notifier.RequestNotifier(FakeFailingApp())
        req = webob.Request.blank('/foo/bar',
                                  environ={'REQUEST_METHOD': 'GET'})
        with mock.patch('openstack.common.notifier.api.notify') as notify:
            try:
                middleware(req)
                self.fail("Application exception has not been re-raised")
            except Exception:
                pass
            call_args = notify.call_args_list[0][0]
            self.assertEqual(call_args[2], 'http.request')
            self.assertEqual(call_args[3], api.INFO)
            self.assertEqual(set(call_args[4].keys()),
                             set(['request', 'exception']))

            request = call_args[4]['request']
            self.assertEqual(request['PATH_INFO'], '/foo/bar')
            self.assertEqual(request['REQUEST_METHOD'], 'GET')
            self.assertFalse(any(map(lambda s: s.startswith('wsgi.'),
                                     request.keys())),
                             "WSGI fields are filtered out")

            exception = call_args[4]['exception']
            self.assertIn('notifier.py', exception['traceback'][0])
            self.assertIn('It happens!', exception['traceback'][-1])
            self.assertEqual(exception['value'], "Exception('It happens!',)")
