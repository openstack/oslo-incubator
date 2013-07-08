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

"""Text Views With Headers

This package defines several text views with headers
"""


class HeaderView(object):
    """A Text View With a Header

    This view simply serializes the model and places the given
    header on top.

    :param header: the header (can be anything on which str() can be called)
    """

    def __init__(self, header):
        self.header = header

    def __call__(self, model):
        return str(self.header) + "\n" + str(model)


class TitledView(HeaderView):
    """A Text View With a Title

    This view simply serializes the model, and places
    a preformatted header containing the given title
    text on top.  The title text can be up to 64 characters
    long.

    :param str title:  the title of the view
    """

    FORMAT_STR = ('=' * 72) + "\n===={0: ^64}====\n" + ('=' * 72)

    def __init__(self, title):
        super(TitledView, self).__init__(self.FORMAT_STR.format(title))
