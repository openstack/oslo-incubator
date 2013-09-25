# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Red Hat, Inc.
# Copyright 2013 IBM Corp.
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

"""
gettext for openstack-common modules.

Usual usage in an openstack.common module:

    from openstack.common.gettextutils import _
"""

import copy
import gettext
import logging
import os
import re

from babel import localedata
import six

_localedir = os.environ.get('oslo'.upper() + '_LOCALEDIR')
_t = gettext.translation('oslo', localedir=_localedir, fallback=True)

_AVAILABLE_LANGUAGES = {}
USE_LAZY = False


def enable_lazy():
    """Convenience function for configuring _() to use lazy gettext

    Call this at the start of execution to enable the gettextutils._
    function to use lazy gettext functionality. This is useful if
    your project is importing _ directly instead of using the
    gettextutils.install() way of importing the _ function.
    """
    global USE_LAZY
    USE_LAZY = True


def _(msg):
    if USE_LAZY:
        message = Message.build_msg({'domain': 'oslo', '_msg': msg})
        return message
    else:
        if six.PY3:
            return _t.gettext(msg)
        return _t.ugettext(msg)


def install(domain, lazy=False):
    """Install a _() function using the given translation domain.

    Given a translation domain, install a _() function using gettext's
    install() function.

    The main difference from gettext.install() is that we allow
    overriding the default localedir (e.g. /usr/share/locale) using
    a translation-domain-specific environment variable (e.g.
    NOVA_LOCALEDIR).

    :param domain: the translation domain
    :param lazy: indicates whether or not to install the lazy _() function.
                 The lazy _() introduces a way to do deferred translation
                 of messages by installing a _ that builds Message objects,
                 instead of strings, which can then be lazily translated into
                 any available locale.
    """
    if lazy:
        # NOTE(mrodden): Lazy gettext functionality.
        #
        # The following introduces a deferred way to do translations on
        # messages in OpenStack. We override the standard _() function
        # and % (format string) operation to build Message objects that can
        # later be translated when we have more information.
        #
        # Also included below is an example LocaleHandler that translates
        # Messages to an associated locale, effectively allowing many logs,
        # each with their own locale.

        def _lazy_gettext(msg):
            """Create and return a Message object.

            Lazy gettext function for a given domain, it is a factory method
            for a project/module to get a lazy gettext function for its own
            translation domain (i.e. nova, glance, cinder, etc.)

            Message encapsulates a string so that we can translate
            it later when needed.
            """
            message = Message.build_msg({'domain': domain, '_msg': msg})
            return message

        from six import moves
        moves.builtins.__dict__['_'] = _lazy_gettext
    else:
        localedir = '%s_LOCALEDIR' % domain.upper()
        if six.PY3:
            gettext.install(domain,
                            localedir=os.environ.get(localedir))
        else:
            gettext.install(domain,
                            localedir=os.environ.get(localedir),
                            unicode=True)


class Message(six.text_type):
    """Class used to encapsulate translatable messages."""
    def __new__(cls, *args, **kwargs):
        """Use for testing only; for run-time use, use build_msg."""
        self = super(Message, cls).__new__(cls, args[0], **kwargs)
        return self

    def __init__(self, *args, **kwargs):
        """Use for testing only; for run-time use, use build_msg."""
        self._msg = args[0]
        self._left_extra_msg = ''
        self._right_extra_msg = ''
        self._locale = None
        self.params = None
        self.domain = args[1]

    @classmethod
    def build_msg(cls, attr):
        """Class method used to construct new Message objects, setting
        the message text (vs. id) to the value retrieved via gettext.
        """
        msg_id = attr['_msg']
        # domain is required, locale is not
        method = cls.get_translation_method(attr['domain'],
                                            attr.get('_locale'))
        left_extra_msg = attr.get('_left_extra_msg') or ''
        right_extra_msg = attr.get('_right_extra_msg') or ''
        msg_txt = left_extra_msg + method(msg_id) + right_extra_msg

        if attr.get('params') is not None:
            msg_txt = msg_txt % attr.get('params')

        msg = cls(six.text_type(msg_txt), attr['domain'])
        msg._set_attributes(attr)
        return msg

    @staticmethod
    def get_translation_method(domain, locale):
        localedir = os.environ.get(domain.upper() + '_LOCALEDIR')
        if locale:
            lang = gettext.translation(domain,
                                       localedir=localedir,
                                       languages=[locale],
                                       fallback=True)
        else:
            # use system locale for translations
            lang = gettext.translation(domain,
                                       localedir=localedir,
                                       fallback=True)

        if six.PY3:
            ugettext = lang.gettext
        else:
            ugettext = lang.ugettext
        return ugettext

    @property
    def locale(self):
        return self._locale

    @staticmethod
    def _set_locale(attr, value):
        params = attr.get('params')
        if not params:
            return

        # This Message object may have been constructed with one or more
        # Message objects as substitution parameters, given as a single
        # Message, or a tuple or Map containing some, so when setting the
        # locale for this Message we need to translate those Messages too.
        if isinstance(params, Message):
            attr['params'] = params.translate_into(value)
            return
        if isinstance(params, tuple):
            contains_msg = False
            for param in params:
                if isinstance(param, Message):
                    contains_msg = True
            if contains_msg:
                new_tup = ()
                for param in params:
                    if isinstance(param, Message):
                        param = param.translate_into(value)
                    new_tup = new_tup + (param, )
                attr['params'] = new_tup
            return
        if isinstance(params, dict):
            for key in params.keys():
                param = params[key]
                if isinstance(param, Message):
                    params[key] = param.translate_into(value)

    @staticmethod
    def _save_dictionary_parameter(full_msg, dict_param):
        # look for %(blah) fields in string;
        # ignore %% and deal with the
        # case where % is first character on the line
        keys = re.findall('(?:[^%]|^)?%\((\w*)\)[a-z]', full_msg)

        # if we don't find any %(blah) blocks but have a %s
        if not keys and re.findall('(?:[^%]|^)%[a-z]', full_msg):
            # apparently the full dictionary is the parameter
            params = copy.deepcopy(dict_param)
        else:
            params = {}
            for key in keys:
                try:
                    params[key] = copy.deepcopy(dict_param[key])
                except TypeError:
                    # cast uncopyable thing to unicode string
                    params[key] = six.text_type(dict_param[key])

        return params

    @staticmethod
    def _save_parameters(attr, other):
        # we check for None later to see if
        # we actually have parameters to inject,
        # so encapsulate if our parameter is actually None
        if other is None:
            attr['params'] = (other, )
        elif isinstance(other, dict):
            # Get the original translated message
            method = Message.get_translation_method(attr['domain'],
                                                    attr.get('locale'))
            text = method(attr['_msg'])
            attr['params'] = Message._save_dictionary_parameter(text, other)
        else:
            # fallback to casting to unicode,
            # this will handle the problematic python code-like
            # objects that cannot be deep-copied
            try:
                attr['params'] = copy.deepcopy(other)
            except TypeError:
                attr['params'] = six.text_type(other)

    def translate_into(self, locale):
        """Operation that results in a new Message object
        translated into the target locale.
        """
        # Create a copy so the source object remains unchanged.
        attr = self._copy_attributes()
        attr['_locale'] = locale
        Message._set_locale(attr, locale)
        return Message.build_msg(attr)

    def __getstate__(self):
        return self._copy_attributes()

    def _copy_attributes(self):
        to_copy = ['_msg', '_right_extra_msg', '_left_extra_msg',
                   'domain', 'params', '_locale']
        new_dict = self.__dict__.fromkeys(to_copy)
        for attr in to_copy:
            new_dict[attr] = copy.deepcopy(self.__dict__[attr])

        return new_dict

    def __setstate__(self, state):
        self._set_attributes(state)

    def _set_attributes(self, state):
        for (k, v) in state.items():
            setattr(self, k, v)

    # operator overloads
    def __add__(self, other):
        attr = self._copy_attributes()
        attr['_right_extra_msg'] += other.__str__()
        return Message.build_msg(attr)

    def __radd__(self, other):
        attr = self._copy_attributes()
        attr['_left_extra_msg'] += other.__str__()
        return Message.build_msg(attr)

    def __mod__(self, other):
        attr = self._copy_attributes()
        Message._save_parameters(attr, other)
        return Message.build_msg(attr)


def get_available_languages(domain):
    """Lists the available languages for the given translation domain.

    :param domain: the domain to get languages for
    """
    if domain in _AVAILABLE_LANGUAGES:
        return copy.copy(_AVAILABLE_LANGUAGES[domain])

    localedir = '%s_LOCALEDIR' % domain.upper()
    find = lambda x: gettext.find(domain,
                                  localedir=os.environ.get(localedir),
                                  languages=[x])

    # NOTE(mrodden): en_US should always be available (and first in case
    # order matters) since our in-line message strings are en_US
    language_list = ['en_US']
    # NOTE(luisg): Babel <1.0 used a function called list(), which was
    # renamed to locale_identifiers() in >=1.0, the requirements master list
    # requires >=0.9.6, uncapped, so defensively work with both. We can remove
    # this check when the master list updates to >=1.0, and all projects udpate
    list_identifiers = (getattr(localedata, 'list', None) or
                        getattr(localedata, 'locale_identifiers'))
    locale_identifiers = list_identifiers()
    for i in locale_identifiers:
        if find(i) is not None:
            language_list.append(i)
    _AVAILABLE_LANGUAGES[domain] = language_list
    return copy.copy(language_list)


def get_localized_message(message, user_locale):
    """Gets a localized version of the given message in the given locale."""
    if isinstance(message, Message):
        return message.translate_into(user_locale)
    else:
        return message


class LocaleHandler(logging.Handler):
    """Handler that can have a locale associated to translate Messages.

    A quick example of how to utilize the Message class above.
    LocaleHandler takes a locale and a target logging.Handler object
    to forward LogRecord objects to after translating the internal Message.
    """

    def __init__(self, locale, target):
        """Initialize a LocaleHandler

        :param locale: locale to use for translating messages
        :param target: logging.Handler object to forward
                       LogRecord objects to after translation
        """
        logging.Handler.__init__(self)
        self.locale = locale
        self.target = target

    def emit(self, record):
        org_msg = record.msg
        if isinstance(org_msg, Message):
            # translate message into the locale
            record.msg = org_msg.translate_into(self.locale)

        self.target.emit(record)

        if isinstance(org_msg, Message):
            # Restore the original message, in case there are other handlers.
            # They should get an unaltered message.
            record.msg = org_msg
