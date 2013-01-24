# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2013 Cloudscaling Group, Inc
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
The MatchMaker classes should except a Topic or Fanout exchange key and
return keys for direct exchanges, per (approximate) AMQP parlance.
"""

from oslo.config import cfg

from openstack.common import importutils
from openstack.common import log as logging
from openstack.common.rpc import matchmaker as mm_common

redis = importutils.try_import('redis')


matchmaker_redis_opts = [
    # Matchmaker ring file
    cfg.StrOpt('matchmaker_redis_host',
               default='127.0.0.1',
               help='Host to locate redis'),
    cfg.IntOpt('matchmaker_redis_port',
               default=6379,
               help='Use this port to connect to redis host.'),
]

CONF = cfg.CONF
CONF.register_opts(matchmaker_redis_opts)
LOG = logging.getLogger(__name__)


class RedisExchange(mm_common.Exchange):
    def __init__(self, matchmaker):
        self.matchmaker = matchmaker
        self.redis = matchmaker.redis
        super(RedisExchange, self).__init__()


class RedisTopicExchange(RedisExchange):
    """
    Exchange where all topic keys are split, sending to second half.
    i.e. "compute.host" sends a message to "compute" running on "host"
    """
    def run(self, topic):
        while True:
            member_name = self.redis.srandmember(topic)

            if not member_name:
                # If this happens, there are no
                # longer any members.
                break

            if not self.matchmaker.is_alive(topic, member_name):
                continue

            host = member_name.split('.', 1)[1]
            return [(member_name, host)]
        return []


class RedisFanoutExchange(RedisExchange):
    """
    Exchange where all topic keys are split, sending to second half.
    i.e. "compute.host" sends a message to "compute" running on "host"
    """
    def run(self, topic):
        topic = topic.split('~', 1)[1]
        hosts = set(self.redis.smembers(topic))
        good_hosts = set(filter(
            lambda host: self.matchmaker.is_alive(topic, host), hosts))

        addresses = map(lambda x: x.split('.', 1)[1], good_hosts)
        return zip(hosts, addresses)


class MatchMakerRedis(mm_common.HeartbeatMatchMakerBase):
    """
    Match Maker where hosts are loaded from a static hashmap.
    """
    def __init__(self):
        super(MatchMakerRedis, self).__init__()

        self.redis = redis.StrictRedis(
            host=CONF.matchmaker_redis_host,
            port=CONF.matchmaker_redis_port)

        self.add_binding(mm_common.FanoutBinding(), RedisFanoutExchange(self))
        self.add_binding(mm_common.DirectBinding(), mm_common.DirectExchange())
        self.add_binding(mm_common.TopicBinding(), RedisTopicExchange(self))

    def ack_alive(self, key):
        return self.redis.expire(key, CONF.matchmaker_heartbeat_ttl)

    def is_alive(self, topic, host):
        if self.redis.ttl(host) == -1:
            self.expire(topic, host)
            return False
        return True

    def expire(self, topic, host):
        with self.redis.pipeline() as pipe:
            pipe.multi()
            pipe.delete(host)
            pipe.srem(topic, host)
            pipe.execute()

    def send_heartbeats(self):
        for htp in self.host_topic:
            key, host = htp
            success = self.ack_alive(key + '.' + host)
            if not success:
                self.register(self.host_topic[host], host)

    def backend_register(self, key, key_host):
        with self.redis.pipeline() as pipe:
            pipe.multi()
            pipe.sadd(key, key_host)

            # No value is needed, we just
            # care if it exists. Sets aren't viable
            # because only keys can expire.
            pipe.set(key_host, '')

            pipe.execute()

    def backend_unregister(self, key, key_host):
        with self.redis.pipeline() as pipe:
            pipe.multi()
            pipe.srem(key, key_host)
            pipe.delete(key_host)
            pipe.execute()
