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

"""Greenthread local storage of variables using weak references"""

import thread
import weakref


def _check_import():
    # NOTE(ldbragst): Here we are checking if we are using Eventlet,
    #                 if not then use threading.local for thread storage.
    try:
        from eventlet import patcher
        if patcher.is_monkey_patched(thread):
            from eventlet import corolocal as local
        else:
            from threading import local
    except ImportError:
        from threading import local

_check_import()


class WeakLocal(local.local):
    def __getattribute__(self, attr):
        rval = local.local.__getattribute__(self, attr)
        if rval:
            # NOTE(mikal): this bit is confusing. What is stored is a weak
            # reference, not the value itself. We therefore need to lookup
            # the weak reference and return the inner value here.
            rval = rval()
        return rval

    def __setattr__(self, attr, value):
        value = weakref.ref(value)
        return local.local.__setattr__(self, attr, value)


# NOTE(mikal): the name "store" should be deprecated in the future
store = WeakLocal()

# A "weak" store uses weak references and allows an object to fall out of scope
# when it falls out of scope in the code that uses the thread local storage. A
# "strong" store will hold a reference to the object so that it never falls out
# of scope.
weak_store = WeakLocal()
strong_store = local.local
