# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import base64
import os
import struct
import time

import requests

from openstack.common.crypto import utils as cryptoutils
from openstack.common import jsonutils
from openstack.common import log as logging


LOG = logging.getLogger(__name__)


class SecureMessageException(Exception):
    """Generic Exception for Secure Messages."""

    msg = "An unknown Secure Message related exception occurred."

    def __init__(self, msg):
        if msg is None:
            msg = self.msg
        super(SecureMessageException, self).__init__(msg)


class SharedKeyNotFound(SecureMessageException):
    """No shared key was found and no other external authentication mechanism
    is available.
    """

    msg = "Shared Key for [%s] Not Found. (%s)"

    def __init__(self, name, errmsg):
        super(SharedKeyNotFound, self).__init__(self.msg % (name, errmsg))


class InvalidMetadata(SecureMessageException):
    """The metadata is invalid."""

    msg = "Invalid metadata: %s"

    def __init__(self, err):
        super(InvalidMetadata, self).__init__(self.msg % err)


class InvalidSignature(SecureMessageException):
    """Signature validation failed."""

    msg = "Failed to validate signature (source=%s, destination=%s)"

    def __init__(self, src, dst):
        super(InvalidSignature, self).__init__(self.msg % (src, dst))


class UnknownDestinationName(SecureMessageException):
    """The Destination name is unknown to us."""

    msg = "Invalid destination name (%s)"

    def __init__(self, name):
        super(UnknownDestinationName, self).__init__(self.msg % name)


class InvalidEncryptedTicket(SecureMessageException):
    """The Encrypted Ticket could not be successfully handled."""

    msg = "Invalid Ticket (source=%s, destination=%s)"

    def __init__(self, src, dst):
        super(InvalidEncryptedTicket, self).__init__(self.msg % (src, dst))


class InvalidExpiredTicket(SecureMessageException):
    """The ticket received is already expired."""

    msg = "Expired ticket (source=%s, destination=%s)"

    def __init__(self, src, dst):
        super(InvalidExpiredTicket, self).__init__(self.msg % (src, dst))


class CommunicationError(SecureMessageException):
    """The Communication with the KDS failed."""

    msg = "Communication Error (target=%s): %s"

    def __init__(self, target, errmsg):
        super(CommunicationError, self).__init__(self.msg % (target, errmsg))


class InvalidArgument(SecureMessageException):
    """Bad initialization argument."""

    msg = "Invalid argument: %s"

    def __init__(self, errmsg):
        super(InvalidArgument, self).__init__(self.msg % errmsg)


class KEYstore(object):
    """A storage class for Signing and Encryption Keys.

    This class creates an object that holds Generic Keys like Signing
    Keys, Encryption Keys, Encrypted SEK Tickets ...

    :param source: the source service
    :param target: the destination service
    """

    def __init__(self):
        self._kvps = dict()

    def _get_key_name(self, source, target, ktype):
        return '%s,%s,%s' % (source, target, ktype)

    def _put(self, src, dst, ktype, expiration, data):
        name = self._get_key_name(src, dst, ktype)
        self._kvps[name] = (expiration, data)

    def _get(self, src, dst, ktype):
        name = self._get_key_name(src, dst, ktype)
        if name in self._kvps:
            expiration, data = self._kvps[name]
            if expiration > time.time():
                return data
            else:
                del self._kvps[name]

        return None

    def clear(self):
        """Wipes the store clear of all data."""
        self._kvps.clear()

    def put_sek(self, source, target, skey, ekey, expiration):
        """Puts a sek pair in the cache.

        :param source: Client name
        :param target: Target name
        :param skey: The Signing Key
        :param ekey: The Encription Key
        :param expiration: Expiration time in seconds since Epoch
        """
        keys = {'skey': skey, 'ekey': ekey}
        self._put(source, target, 'sek', expiration, keys)

    def get_sek(self, source, target):
        return self._get(source, target, 'sek')

    def put_ticket(self, source, target, skey, ekey, esek, expiration):
        """Puts a sek pair in the cache.

        :param source: Client name
        :param target: Target name
        :param skey: The Signing Key
        :param ekey: The Encription Key
        :param expiration: Expiration time in seconds since Epoch
        """
        keys = {'skey': skey, 'ekey': ekey, 'esek': esek}
        self._put(source, target, 'ticket', expiration, keys)

    def get_ticket(self, source, target):
        return self._get(source, target, 'ticket')


KEY_STORE = None


class KDSClient(object):

    USER_AGENT = 'oslo-incubator/rpc'

    def __init__(self, endpoint=None, timeout=None):
        """A KDS Client class."""

        self._endpoint = endpoint
        if timeout is not None:
            self.timeout = float(timeout)
        else:
            self.timeout = None

    def _do_get(self, url, request):
        req_kwargs = dict()
        req_kwargs['headers'] = dict()
        req_kwargs['headers']['User-Agent'] = self.USER_AGENT
        req_kwargs['headers']['Content-Type'] = 'application/json'
        req_kwargs['data'] = jsonutils.dumps({'request': request})
        if self.timeout is not None:
            req_kwargs['timeout'] = self.timeout

        try:
            resp = requests.get(url, **req_kwargs)
        except requests.ConnectionError as e:
            err = "Unable to establish connection. %s" % e
            raise CommunicationError(url, err)

        return resp

    def _get_reply(self, url, resp):
        if resp.text:
            try:
                body = jsonutils.loads(resp.text)
                reply = body['reply']
            except (ValueError, TypeError):
                msg = "Failed to decode reply: %s" % resp.text
                raise CommunicationError(url, msg)
        else:
            msg = "No reply data was returned."
            raise CommunicationError(url, msg)

        return reply

    def get_ticket(self, request, url=None, redirects=10):
        """Send an HTTP request.

        Wraps around 'requests' to handle redirects and common errors.
        """
        if url is None:
            if self._endpoint is None or len(self._endpoint) == 0:
                raise CommunicationError(url, 'Endpoint not configured')
            url = self._endpoint + '/kds/ticket'

        while redirects:
            resp = self._do_get(url, request)
            if resp.status_code in (301, 302, 305):
                # Redirected. Reissue the request to the new location.
                url = resp.headers['location']
                redirects -= 1
                continue
            elif resp.status_code != 200:
                msg = "Request returned failure status: %s (%s)"
                err = msg % (resp.status_code, resp.text)
                raise CommunicationError(url, err)

            return self._get_reply(url, resp)

        # too many redirects
        raise CommunicationError(url, "Too many redirections, giving up!")


# we need to keep a global nonce, as this value should never repeat non matter
# howmany SecureMessage objects we create
_NONCE = None


class SecureMessage(object):
    """A Secure Message object.

    This class creates a signing/encryption facility for RPC messages.
    It encapsulates all the necessary crypto primitives to insulate
    regular code from the intricacies of message authentication, validation
    and optionally encryption.

    :param name: The endpoint name, this is used to source signing keys, and
                   verify incoming messages. It is a tuple (topic, host)
    :param conf: a oslo.config object
    :param key: (optional) explicitly pass in endpoint private key.
                  If not provided it will be sourced from the service config
    :param key_store: (optional) Storage class for local caching
    :param encrypt: (defaults to False) Whether to encrypt messages
    :param enctype: (defaults to AES) Cipher to use
    :param hashtype: (defaults to SHA256) Hash function to use for signatures
    """

    def __init__(self, name, conf, key=None, key_store=None,
                 encrypt=False, enctype='AES', hashtype='SHA256'):

        if not name:
            raise InvalidArgument("Name cannot be None or Empty")
        if not conf:
            raise InvalidArgument("Conf must be provided")

        self._name = '%s.%s' % name
        self._key = key
        self._conf = conf
        self._encrypt = encrypt
        self._crypto = cryptoutils.SymmetricCrypto(enctype, hashtype)
        self._hkdf = cryptoutils.HKDF(hashtype)
        self._kds = KDSClient(self._conf.kds_endpoint)

        if self._key is None:
            keys = None
            if self._conf.secure_message_keyfile:
                with open(self._conf.secure_message_keyfile, 'r') as f:
                    keys = f.readlines()
            elif self._conf.secure_message_key:
                keys = self._conf.secure_message_key

            for k in keys:
                if k[0] == '#':
                    continue
                if ':' not in k:
                    break
                svc, key = k.split(':')
                if svc == name[0] or svc == self._name:
                    self._key = base64.b64decode(key)
                    break
        if self._key is None:
            err = "Secure_message_key[file] options missing or malformed"
            raise SharedKeyNotFound(name, err)

        global KEY_STORE
        if key_store is None:
            if KEY_STORE is None:
                KEY_STORE = KEYstore()
        else:
            KEY_STORE = key_store
        self._key_store = KEY_STORE

    def _split_key(self, key, size):
        sig_key = key[:size]
        enc_key = key[size:]
        return sig_key, enc_key

    def _decode_esek(self, key, source, target, timestamp, esek):
        """This function decrypts the esek buffer passed in and returns a
        KEYstore to be used to check and decrypt the received message.

        :param key: The key to use to decrypt the ticket (esek)
        :param source: The name of the source service
        :param traget: The name of the target service
        :param timestamp: The incoming message timestamp
        :param esek: a base64 encoded encrypted block containing a JSON string
        """
        rkey = None

        try:
            s = self._crypto.decrypt(key, esek)
            j = jsonutils.loads(s)

            rkey = base64.b64decode(j['key'])
            expiration = j['timestamp'] + j['ttl']
            if j['timestamp'] > timestamp or timestamp > expiration:
                raise InvalidExpiredTicket(source, target)

        except Exception:
            raise InvalidEncryptedTicket(source, target)

        info = '%s,%s,%s' % (source, target, str(j['timestamp']))

        sek = self._hkdf.expand(rkey, info, len(key) * 2)

        skey, ekey = self._split_key(sek, len(key))
        self._key_store.put_sek(source, target, skey, ekey, expiration)
        return skey, ekey

    def _get_ticket(self, target):
        """This function will check if we already have a SEK for the specified
        target in the cache, or will go and try to fetch a new SEK from the key
        server.

        :param target: The name of the target service
        """
        tkt = self._key_store.get_ticket(self._name, target)

        if tkt is not None:
            return tkt

        #prepare metadata
        md = {'requestor': self._name,
              'target': target,
              'timestamp': time.time(),
              'nonce': struct.unpack('Q', os.urandom(8))[0]}
        metadata = base64.b64encode(jsonutils.dumps(md))

        # sign metadata
        signature = self._crypto.sign(self._key, metadata)

        # HTTP request
        reply = self._kds.get_ticket({'metadata': metadata,
                                      'signature': signature})

        # Verify reply
        signature = self._crypto.sign(self._key,
                                      (reply['metadata'] + reply['ticket']))
        if signature != reply['signature']:
            raise InvalidEncryptedTicket(md['source'], md['destination'])
        md = jsonutils.loads(base64.b64decode(reply['metadata']))
        if (((md['source'] != self._name) or
             (md['destination'] != target) or
             (md['expiration'] < time.time()))):
            raise InvalidEncryptedTicket(md['source'], md['destination'])

        #return ticket data
        tkt = self._crypto.decrypt(self._key, reply['ticket'])
        tkt = jsonutils.loads(tkt)

        self._key_store.put_ticket(self._name, target,
                                   base64.b64decode(tkt['skey']),
                                   base64.b64decode(tkt['ekey']),
                                   tkt['esek'], md['expiration'])
        return self._key_store.get_ticket(self._name, target)

    def _get_nonce(self):
        """We keep a single counter per instance, as it is so huge we can't
        possibly cycle through within 1/100 of a second anyway.
        """

        global _NONCE
        # Lazy initialize, for now get a random value, multiply by 2^32 and
        # use it as the nonce base. The counter itself will rotate after
        # 2^32 increments.
        if _NONCE is None:
            _NONCE = [struct.unpack('I', os.urandom(4))[0], 0]

        # Increment counter and wrap at 2^32
        _NONCE[1] += 1
        if _NONCE[1] > 0xffffffff:
            _NONCE[1] = 0

        # Return base + counter
        return long((_NONCE[0] * 0xffffffff)) + _NONCE[1]

    def encode(self, version, target, json_msg):
        """This is the main encoding function.

        It takes a target and a message and returns a tuple consisting of a
        JSON serialized metadata object, a JSON serialized (and optionally
        encrypted) message, and a signature.

        :param version: the current envelope version
        :param target: The name of the target service (usually with hostname)
        :param json_msg: a serialized json message object
        """
        ticket = self._get_ticket(target)

        metadata = jsonutils.dumps({'source': self._name,
                                    'destination': target,
                                    'timestamp': time.time(),
                                    'nonce': self._get_nonce(),
                                    'esek': ticket['esek'],
                                    'encryption': self._encrypt})

        message = json_msg
        if self._encrypt:
            message = self._crypto.encrypt(ticket['ekey'], message)

        signature = self._crypto.sign(ticket['skey'],
                                      version + metadata + message)

        return (metadata, message, signature)

    def decode(self, version, metadata, message, signature):
        """This is the main decoding function.

        It takes a version, metadata, message and signature strings and
        returns a tuple with a (decrypted) message and metadata or raises
        an exception in case of error.

        :param version: the current envelope version
        :param metadata: a JSON serialized object with metadata for validation
        :param message: a JSON serialized (base64 encoded encrypted) message
        :param signature: a base64 encoded signature
        """
        md = jsonutils.loads(metadata)

        check_args = ('source', 'destination', 'timestamp',
                      'nonce', 'esek', 'encryption')
        for arg in check_args:
            if arg not in md:
                raise InvalidMetadata('Missing argument "%s"' % arg)

        if md['destination'] != self._name:
            # TODO(simo) handle group keys by checking target
            raise UnknownDestinationName(md['destination'])

        try:
            skey, ekey = self._decode_esek(self._key,
                                           md['source'], md['destination'],
                                           md['timestamp'], md['esek'])
        except InvalidExpiredTicket:
            raise
        except Exception:
            raise InvalidMetadata('Failed to decode ESEK for %s/%s' % (
                                  md['source'], md['destination']))

        sig = self._crypto.sign(skey, version + metadata + message)

        if sig != signature:
            raise InvalidSignature(md['source'], md['destination'])

        if md['encryption'] is True:
            msg = self._crypto.decrypt(ekey, message)
        else:
            msg = message

        return (md, msg)
