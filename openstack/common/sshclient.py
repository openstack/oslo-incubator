# Copyright 2013: Mirantis Inc.
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


"""High level ssh library.

Usage examples:

Simply execute command with small output:

    ssh = sshclient.SSH('root', 'example.com', port=33)
    status, stdout, stderr = ssh.execute('ps ax')
    if status:
        raise Exception('Command failed with non-zero exit status.')
    print stdout.splitlnes()

Execute command with huge output:

    def stdout_callback(data):
        LOG.debug(data)
    ssh = sshclient.SSH('root', 'example.com')
    ssh.run('tail -f /var/log/syslog', stdout_callback=stdout_callback,
            timeout=False)

Execute local script on remote side:

    ssh = sshclient.SSH('user', 'example.com')
    status, out, err = ssh.execute('/bin/sh -s arg1 arg2',
                                   stdin=open('~/myscript.sh', 'r'))

Upload file:

    ssh = sshclient.SSH('user', 'example.com')
    ssh.run('cat > ~/upload/file.gz', stdin=open('/store/file.gz', 'rb'))

Eventlet:

    eventlet.monkey_patch(select=True, time=True)
    or
    eventlet.monkey_patch()
    or
    sshclient = eventlet.import_patched("opentstack.common.sshclient")

"""

import os
import paramiko
import select
import socket
import time

from openstack.common.gettextutils import _
from openstack.common import log as logging


LOG = logging.getLogger(__name__)


class SSHError(Exception):
    pass


class SSHTimeout(SSHError):
    pass


class SSH(object):
    """Represent ssh connection."""

    def __init__(self, user, host, port=22, key=None, password=None):
        """Initialize SSH client."""

        self.user = user
        self.host = host
        self.port = port
        self.password = password
        self.key = key or os.path.expanduser('~/.ssh/id_rsa')

        if not os.path.isfile(self.key):
            raise SSHError('Invalid key file')

    def _get_client(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.host, username=self.user, port=self.port,
                       key_filename=self.key, password=self.password)
        return client

    def run(self, cmd, stdin=None, stdout_callback=None, stderr_callback=None,
            raise_on_error=True, timeout=3600):
        """Execute specified command on the server.

        :param cmd:             Command to be executed.
        :param stdin:           Open file to be send to command's stdin.
        :param stdout_callback: Callback for stdout data handling.
        :param stderr_callback: Callback for stderr data handling.
        :param raise_on_error:  If False then exit code will be return. If True
                                then exception will be raized if non-zero code.
        :param timeout:         Timeout in seconds for command execution.
                                Default 1 hour.
        """
        client = paramiko.SSHClient()
        try:
            exit_status = self._run(client, cmd, stdin=stdin,
                                    stdout_callback=stdout_callback,
                                    stderr_callback=stderr_callback,
                                    raise_on_error=raise_on_error,
                                    timeout=timeout)
        finally:
            client.close()
        return exit_status

    def _run(self, client, cmd, stdin=None, stdout_callback=None,
             stderr_callback=None, raise_on_error=True, timeout=3600):

        client = self._get_client()

        transport = client.get_transport()
        session = transport.open_session()
        session.exec_command(cmd)
        start_time = time.time()

        data_to_send = ''
        stderr_data = None

        while True:
            r, w, e = select.select([session], [session], [session], 1)

            if session.recv_ready():
                data = session.recv(4096)
                LOG.debug(_('stdout: %r') % data)
                if stdout_callback is not None:
                    stdout_callback(data)
                continue

            if session.recv_stderr_ready():
                stderr_data = session.recv_stderr(4096)
                LOG.debug(_('stderr: %r') % stderr_data)
                if stderr_callback is not None:
                    stderr_callback(stderr_data)
                continue

            if session.send_ready():
                if stdin is not None and not stdin.closed:
                    if not data_to_send:
                        data_to_send = stdin.read(4096)
                        if not data_to_send:
                            stdin.close()
                            session.shutdown(1)
                            continue
                    sent_bytes = session.send(data_to_send)
                    data_to_send = data_to_send[sent_bytes:]

            if session.exit_status_ready():
                break

            if timeout and (time.time() - timeout) > start_time:
                args = {'cmd': cmd, 'host': self.host}
                raise SSHTimeout(_('Timeout executing command '
                                   '"%(cmd)s" on host %(host)s') % args)
            if e:
                raise SSHError('Socket error.')

        exit_status = session.recv_exit_status()
        if 0 != exit_status and raise_on_error:
            details = _('Command failed with exit_status %d.') % exit_status
            if stderr_data:
                details += _(' Last stderr data: "%s".') % stderr_data
            raise SSHError(details)
        return exit_status

    def execute(self, cmd, stdin=None, timeout=3600):
        """Execute the specified command on the server.

        :param cmd:     Command to be executed.
        :param stdin:   Open file to be sent on process stdin.
        :param timeout: Timeout for execution of the command.

        Return tuple (exit_status, stdout, stderr)

        """
        stdout = ['']
        stderr = ['']

        def stderr_callback(data):
            stderr[0] += data

        def stdout_callback(data):
            stdout[0] += data

        exit_status = self.run(cmd, stderr_callback=stderr_callback,
                               stdout_callback=stdout_callback, stdin=stdin,
                               timeout=timeout, raise_on_error=False)
        return (exit_status, stdout[0], stderr[0])

    def wait(self, timeout=120, interval=1):
        """Wait for the host will be available via ssh."""
        start_time = time.time()
        while True:
            try:
                return self.execute('uname')
            except (socket.error, SSHError) as e:
                LOG.debug(_('Ssh is still unavailable: %r') % e)
                time.sleep(interval)
            if (time.time() - timeout) > start_time:
                raise SSHTimeout(_('Timeout waiting for "%s"') % self.host)
