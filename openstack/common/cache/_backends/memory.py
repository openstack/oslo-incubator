# Copyright 2013 Red Hat, Inc.
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


from openstack.common.cache import backends
from openstack.common import lockutils
from openstack.common import timeutils


class MemoryBackend(backends.BaseCache):

    def __init__(self, conf, group, cache_namespace):
        super(MemoryBackend, self).__init__(conf, group, cache_namespace)
        self._cache = {}
        self._keys_expires = {}

    def _set_unlocked(self, key, value, ttl=0):
        expires_at = 0
        if ttl != 0:
            expires_at = timeutils.utcnow_ts() + ttl

        self._cache[key] = (expires_at, value)

        if expires_at:
            self._keys_expires.setdefault(expires_at, set()).add(key)

        return True

    def set(self, key, value, ttl=0):
        key = self._prepare_key(key)
        with lockutils.lock(key):
            self._set_unlocked(key, value, ttl)

    def _get_unlocked(self, key, default=None):
        now = timeutils.utcnow_ts()
        try:
            timeout, value = self._cache[key]

            if timeout and now >= timeout:

                # NOTE(flaper87): Record expired,
                # remove it from the cache but catch
                # KeyError and ValueError in case
                # _purge_expired removed this key already.
                try:
                    del self._cache[key]
                except KeyError:
                    pass

                try:
                    # NOTE(flaper87): Keys with ttl == 0
                    # don't exist in the _keys_expires dict
                    self._keys_expires[timeout].remove(key)
                except (KeyError, ValueError):
                    pass

                return (0, default)

            return (timeout, value)
        except KeyError:
            return (0, default)

    def get(self, key, default=None):
        key = self._prepare_key(key)
        with lockutils.lock(key):
            return self._get_unlocked(key)[1]

    def exists(self, key):
        key = self._prepare_key(key)

        with lockutils.lock(key):
            now = timeutils.utcnow_ts()
            try:
                timeout, value = self._cache[key]
                return not timeout or now <= timeout
            except KeyError:
                return False

    def _incr_append(self, key, other):
        key = self._prepare_key(key)
        with lockutils.lock(key):
            timeout, value = self._get_unlocked(key)

            if value is None:
                return None

            ttl = timeutils.utcnow_ts() - timeout
            new_value = value + other
            self._set_unlocked(key, new_value, ttl)
            return new_value

    def incr(self, key, delta=1):
        return self._incr_append(key, delta)

    def append(self, key, tail):
        return self._incr_append(key, tail)

    def _purge_expired(self):
        """Removes expired keys from the cache."""

        now = timeutils.utcnow_ts()
        for timeout in sorted(self._keys_expires.keys()):

            # NOTE(flaper87): If timeout is greater
            # than `now`, stop the iteration, remaining
            # keys have not expired.
            if now < timeout:
                break

            # NOTE(flaper87): Unset every key in
            # this set from the cache if its timeout
            # is equal to `timeout`. (The key might
            # have been updated)
            for subkey in self._keys_expires.pop(timeout):
                try:
                    if self._cache[subkey][0] == timeout:
                        del self._cache[subkey]
                except KeyError:
                    continue

    def unset(self, key):
        self._purge_expired()

        # NOTE(flaper87): Delete the key. Using pop
        # since it could have been deleted already
        value = self._cache.pop(self._prepare_key(key), None)

        if value:
            try:
                # NOTE(flaper87): Keys with ttl == 0
                # don't exist in the _keys_expires dict
                self._keys_expires[value[0]].remove(value[1])
            except (KeyError, ValueError):
                pass

    def flush(self):
        self._cache = {}
        self._keys_expires = {}
