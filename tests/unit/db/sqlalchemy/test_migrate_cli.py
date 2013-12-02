# Copyright 2013 Mirantis Inc.
# All Rights Reserved
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
#
import sys

import mock
from oslo.config import cfg


from openstack.common import test

from openstack.common.db.sqlalchemy import migration_cli
from openstack.common.db.sqlalchemy.migration_cli import extensions


@mock.patch(('openstack.common.db.sqlalchemy.migration_cli.'
             'extensions.alembic.command'))
class TestAlembicExtension(test.BaseTestCase):

    def setUp(self):
        cfg.CONF.database.alembic_ini_path = 'test'
        self.alembic = extensions.AlembicExtension()
        super(TestAlembicExtension, self).setUp()

    def test_check_available_true(self, command):
        """Verifies that check_available returns True on non empty
        alembic_ini_path conf variable
        """
        self.assertTrue(extensions.AlembicExtension.check_available())

    def test_check_available_false(self, command):
        """Verifies check_available returns Fakse on empty
        alembic_ini_path variable
        """
        cfg.CONF.database.alembic_ini_path = ''
        self.assertFalse(extensions.AlembicExtension.check_available())

    def test_upgrade_none(self, command):
        self.alembic.upgrade(None)
        command.upgrade.assert_called_once_with(self.alembic.config, 'head')

    def test_upgrade_normal(self, command):
        self.alembic.upgrade('131daa')
        command.upgrade.assert_called_once_with(self.alembic.config, '131daa')

    def test_downgrade_none(self, command):
        self.alembic.downgrade(None)
        command.downgrade.assert_called_once_with(self.alembic.config, 'base')

    def test_downgrade_int(self, command):
        self.alembic.downgrade(111)
        command.downgrade.assert_called_once_with(self.alembic.config, 'base')

    def test_downgrade_normal(self, command):
        self.alembic.downgrade('131daa')
        command.downgrade.assert_called_once_with(
            self.alembic.config, '131daa')

    def test_revision(self, command):
        self.alembic.revision(message='test', autogenerate=True)
        command.revision.assert_called_once_with(
            self.alembic.config, message='test', autogenerate=True)

    def test_stamp(self, command):
        self.alembic.stamp('stamp')
        command.stamp.assert_called_once_with(
            self.alembic.config, revision='stamp')

    def test_version(self, command):
        version = self.alembic.version()
        self.assertEqual(version, None)


@mock.patch(('openstack.common.db.sqlalchemy.migration_cli.'
             'extensions.migration'))
class TestMigrateExtension(test.BaseTestCase):

    def setUp(self):
        cfg.CONF.database.migrate_repo_path = 'test'
        self.migrate = extensions.MigrateExtension()
        super(TestMigrateExtension, self).setUp()

    def test_check_available_true(self, migration):
        self.assertTrue(extensions.MigrateExtension.check_available())

    def test_check_available_false(self, migration):
        cfg.CONF.database.migrate_repo_path = ''
        self.assertFalse(extensions.MigrateExtension.check_available())

    def test_upgrade_head(self, migration):
        self.migrate.upgrade('head')
        migration.db_sync.assert_called_once_with(
            self.migrate.repository, None)

    def test_upgrade_normal(self, migration):
        self.migrate.upgrade(111)
        migration.db_sync.assert_called_once_with(
            self.migrate.repository, 111)

    def test_downgrade_init_version_from_base(self, migration):
        self.migrate.downgrade('base')
        migration.db_sync.assert_called_once_with(
            self.migrate.repository, cfg.CONF.database.init_version)

    def test_downgrade_init_version_from_none(self, migration):
        self.migrate.downgrade(None)
        migration.db_sync.assert_called_once_with(
            self.migrate.repository, cfg.CONF.database.init_version)

    def test_downgrade_normal(self, migration):
        self.migrate.downgrade(101)
        migration.db_sync.assert_called_once_with(
            self.migrate.repository, 101)

    def test_version(self, migration):
        self.migrate.version()
        migration.db_version.assert_called_once_with(self.migrate.repository)


class TestMigrationManager(test.BaseTestCase):

    def setUp(self):
        self.migration_manager = migration_cli.get_migration_manager()
        self.ext = mock.Mock()
        self.migration_manager.extensions = [self.ext]
        super(TestMigrationManager, self).setUp()
        self.addCleanup(migration_cli.cfg.CONF.reset)

    def test_manager_update(self):
        argv = ['migrate_cli', 'upgrade', 'head']
        with mock.patch.object(sys, 'argv', argv):
            migration_cli.main()
        self.ext.obj.upgrade.assert_called_once_with('head')

    def test_manager_update_revision_none(self):
        argv = ['migrate_cli', 'upgrade']
        with mock.patch.object(sys, 'argv', argv):
            migration_cli.main()
        self.ext.obj.upgrade.assert_called_once_with(None)

    def test_downgrade_normal_revision(self):
        argv = ['migrate_cli', 'downgrade', '111abcd']
        with mock.patch.object(sys, 'argv', argv):
            migration_cli.main()
        self.ext.obj.downgrade.assert_called_once_with('111abcd')

    def test_version(self):
        argv = ['migrate_cli', 'version']
        with mock.patch.object(sys, 'argv', argv):
            migration_cli.main()
        self.ext.obj.version.assert_called_once_with()

    def test_revision_message_autogenerate(self):
        argv = ['migrate_cli', 'revision', '--message', 'test',
                '--autogenerate']
        with mock.patch.object(sys, 'argv', argv):
            migration_cli.main()
        self.ext.obj.revision('test', True)

    def test_revision_only_message(self):
        argv = ['migrate_cli', 'revision', '--message', 'test']
        with mock.patch.object(sys, 'argv', argv):
            migration_cli.main()
        self.ext.obj.revision('test', False)

    def test_stamp(self):
        argv = ['migrate_cli', 'stamp', 'stamp']
        with mock.patch.object(sys, 'argv', argv):
            migration_cli.main()
        self.ext.obj.stamp('stamp')
