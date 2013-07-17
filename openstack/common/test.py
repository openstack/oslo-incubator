#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack Foundation
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

"""Common utilities used in testing"""

import os
import tempfile

import fixtures
from oslo.config import cfg
import testtools

from openstack.common import exception
from openstack.common.fixture import moxstubout

CONF = cfg.CONF


class BaseTestCase(testtools.TestCase):

    def setUp(self, conf=cfg.CONF):
        super(BaseTestCase, self).setUp()
        test_timeout = os.environ.get('OS_TEST_TIMEOUT', 0)
        try:
            test_timeout = int(test_timeout)
        except ValueError:
            # If timeout value is invalid do not set a timeout.
            test_timeout = 0
        if test_timeout > 0:
            self.useFixture(fixtures.Timeout(test_timeout, gentle=True))
        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())
        if (os.environ.get('OS_STDOUT_CAPTURE') == 'True' or
                os.environ.get('OS_STDOUT_CAPTURE') == '1'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if (os.environ.get('OS_STDERR_CAPTURE') == 'True' or
                os.environ.get('OS_STDERR_CAPTURE') == '1'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))
        moxfixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = moxfixture.mox
        self.stubs = moxfixture.stubs
        self.conf = conf
        self.addCleanup(CONF.reset)
        self.addCleanup(self.stubs.UnsetAll)
        self.addCleanup(self.stubs.SmartUnsetAll)
        self.useFixture(fixtures.FakeLogger('openstack.common'))
        self.stubs.Set(exception, '_FATAL_EXCEPTION_FORMAT_ERRORS', True)
        self.tempdirs = []


def config(**kw):
    """Override some configuration values.

    The keyword arguments are the names of configuration options to
    override and their values.

    If a group argument is supplied, the overrides are applied to
    the specified configuration option group.

    All overrides are automatically cleared at the end of the current
    test by the tearDown() method.
    """
    group = kw.pop('group', None)
    for k, v in kw.iteritems():
        CONF.set_override(k, v, group)


def create_tempfiles(files, ext='.conf'):
    tempfiles = []
    for (basename, contents) in files:
        if not os.path.isabs(basename):
            (fd, path) = tempfile.mkstemp(prefix=basename, suffix=ext)
        else:
            path = basename + ext
            fd = os.open(path, os.O_CREAT | os.O_WRONLY)
        tempfiles.append(path)
        try:
            os.write(fd, contents)
        finally:
            os.close(fd)
    return tempfiles
