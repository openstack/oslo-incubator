# Copyright 2010-2011 OpenStack Foundation
# Copyright 2012-2013 IBM Corp.
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

import abc
import functools
import logging
import os
import pprint
import subprocess

import alembic
import alembic.autogenerate
import alembic.migration
import lockfile
import six
from six import moves
from six.moves.urllib import parse
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.sql.expression as expr
import sqlalchemy.types as types

from openstack.common.db.sqlalchemy import utils
from openstack.common.gettextutils import _LE
from openstack.common import test

LOG = logging.getLogger(__name__)


def _have_mysql(user, passwd, database):
    present = os.environ.get('TEST_MYSQL_PRESENT')
    if present is None:
        return utils.is_backend_avail(backend='mysql',
                                      user=user,
                                      passwd=passwd,
                                      database=database)
    return present.lower() in ('', 'true')


def _have_postgresql(user, passwd, database):
    present = os.environ.get('TEST_POSTGRESQL_PRESENT')
    if present is None:
        return utils.is_backend_avail(backend='postgres',
                                      user=user,
                                      passwd=passwd,
                                      database=database)
    return present.lower() in ('', 'true')


def _set_db_lock(lock_path=None, lock_prefix=None):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                path = lock_path or os.environ.get("OSLO_LOCK_PATH")
                lock = lockfile.FileLock(os.path.join(path, lock_prefix))
                with lock:
                    LOG.debug('Got lock "%s"' % f.__name__)
                    return f(*args, **kwargs)
            finally:
                LOG.debug('Lock released "%s"' % f.__name__)
        return wrapper
    return decorator


class BaseMigrationTestCase(test.BaseTestCase):
    """Base class fort testing of migration utils."""

    def __init__(self, *args, **kwargs):
        super(BaseMigrationTestCase, self).__init__(*args, **kwargs)

        self.DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                                'test_migrations.conf')
        # Test machines can set the TEST_MIGRATIONS_CONF variable
        # to override the location of the config file for migration testing
        self.CONFIG_FILE_PATH = os.environ.get('TEST_MIGRATIONS_CONF',
                                               self.DEFAULT_CONFIG_FILE)
        self.test_databases = {}
        self.migration_api = None

    def setUp(self):
        super(BaseMigrationTestCase, self).setUp()

        # Load test databases from the config file. Only do this
        # once. No need to re-run this on each test...
        LOG.debug('config_path is %s' % self.CONFIG_FILE_PATH)
        if os.path.exists(self.CONFIG_FILE_PATH):
            cp = moves.configparser.RawConfigParser()
            try:
                cp.read(self.CONFIG_FILE_PATH)
                defaults = cp.defaults()
                for key, value in defaults.items():
                    self.test_databases[key] = value
            except moves.configparser.ParsingError as e:
                self.fail("Failed to read test_migrations.conf config "
                          "file. Got error: %s" % e)
        else:
            self.fail("Failed to find test_migrations.conf config "
                      "file.")

        self.engines = {}
        for key, value in self.test_databases.items():
            self.engines[key] = sqlalchemy.create_engine(value)

        # We start each test case with a completely blank slate.
        self._reset_databases()

    def tearDown(self):
        # We destroy the test data store between each test case,
        # and recreate it, which ensures that we have no side-effects
        # from the tests
        self._reset_databases()
        super(BaseMigrationTestCase, self).tearDown()

    def execute_cmd(self, cmd=None):
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        output = process.communicate()[0]
        LOG.debug(output)
        self.assertEqual(0, process.returncode,
                         "Failed to run: %s\n%s" % (cmd, output))

    def _reset_pg(self, conn_pieces):
        (user,
         password,
         database,
         host) = utils.get_db_connection_info(conn_pieces)
        os.environ['PGPASSWORD'] = password
        os.environ['PGUSER'] = user
        # note(boris-42): We must create and drop database, we can't
        # drop database which we have connected to, so for such
        # operations there is a special database template1.
        sqlcmd = ("psql -w -U %(user)s -h %(host)s -c"
                  " '%(sql)s' -d template1")

        sql = ("drop database if exists %s;") % database
        droptable = sqlcmd % {'user': user, 'host': host, 'sql': sql}
        self.execute_cmd(droptable)

        sql = ("create database %s;") % database
        createtable = sqlcmd % {'user': user, 'host': host, 'sql': sql}
        self.execute_cmd(createtable)

        os.unsetenv('PGPASSWORD')
        os.unsetenv('PGUSER')

    @_set_db_lock(lock_prefix='migration_tests-')
    def _reset_databases(self):
        for key, engine in self.engines.items():
            conn_string = self.test_databases[key]
            conn_pieces = parse.urlparse(conn_string)
            engine.dispose()
            if conn_string.startswith('sqlite'):
                # We can just delete the SQLite database, which is
                # the easiest and cleanest solution
                db_path = conn_pieces.path.strip('/')
                if os.path.exists(db_path):
                    os.unlink(db_path)
                # No need to recreate the SQLite DB. SQLite will
                # create it for us if it's not there...
            elif conn_string.startswith('mysql'):
                # We can execute the MySQL client to destroy and re-create
                # the MYSQL database, which is easier and less error-prone
                # than using SQLAlchemy to do this via MetaData...trust me.
                (user, password, database, host) = \
                    utils.get_db_connection_info(conn_pieces)
                sql = ("drop database if exists %(db)s; "
                       "create database %(db)s;") % {'db': database}
                cmd = ("mysql -u \"%(user)s\" -p\"%(password)s\" -h %(host)s "
                       "-e \"%(sql)s\"") % {'user': user, 'password': password,
                                            'host': host, 'sql': sql}
                self.execute_cmd(cmd)
            elif conn_string.startswith('postgresql'):
                self._reset_pg(conn_pieces)


class WalkVersionsMixin(object):
    def _walk_versions(self, engine=None, snake_walk=False, downgrade=True):
        # Determine latest version script from the repo, then
        # upgrade from 1 through to the latest, with no data
        # in the databases. This just checks that the schema itself
        # upgrades successfully.

        # Place the database under version control
        self.migration_api.version_control(engine, self.REPOSITORY,
                                           self.INIT_VERSION)
        self.assertEqual(self.INIT_VERSION,
                         self.migration_api.db_version(engine,
                                                       self.REPOSITORY))

        LOG.debug('latest version is %s' % self.REPOSITORY.latest)
        versions = range(self.INIT_VERSION + 1, self.REPOSITORY.latest + 1)

        for version in versions:
            # upgrade -> downgrade -> upgrade
            self._migrate_up(engine, version, with_data=True)
            if snake_walk:
                downgraded = self._migrate_down(
                    engine, version - 1, with_data=True)
                if downgraded:
                    self._migrate_up(engine, version)

        if downgrade:
            # Now walk it back down to 0 from the latest, testing
            # the downgrade paths.
            for version in reversed(versions):
                # downgrade -> upgrade -> downgrade
                downgraded = self._migrate_down(engine, version - 1)

                if snake_walk and downgraded:
                    self._migrate_up(engine, version)
                    self._migrate_down(engine, version - 1)

    def _migrate_down(self, engine, version, with_data=False):
        try:
            self.migration_api.downgrade(engine, self.REPOSITORY, version)
        except NotImplementedError:
            # NOTE(sirp): some migrations, namely release-level
            # migrations, don't support a downgrade.
            return False

        self.assertEqual(
            version, self.migration_api.db_version(engine, self.REPOSITORY))

        # NOTE(sirp): `version` is what we're downgrading to (i.e. the 'target'
        # version). So if we have any downgrade checks, they need to be run for
        # the previous (higher numbered) migration.
        if with_data:
            post_downgrade = getattr(
                self, "_post_downgrade_%03d" % (version + 1), None)
            if post_downgrade:
                post_downgrade(engine)

        return True

    def _migrate_up(self, engine, version, with_data=False):
        """migrate up to a new version of the db.

        We allow for data insertion and post checks at every
        migration version with special _pre_upgrade_### and
        _check_### functions in the main test.
        """
        # NOTE(sdague): try block is here because it's impossible to debug
        # where a failed data migration happens otherwise
        try:
            if with_data:
                data = None
                pre_upgrade = getattr(
                    self, "_pre_upgrade_%03d" % version, None)
                if pre_upgrade:
                    data = pre_upgrade(engine)

            self.migration_api.upgrade(engine, self.REPOSITORY, version)
            self.assertEqual(version,
                             self.migration_api.db_version(engine,
                                                           self.REPOSITORY))
            if with_data:
                check = getattr(self, "_check_%03d" % version, None)
                if check:
                    check(engine, data)
        except Exception:
            LOG.error(_LE("Failed to migrate to version %s on engine %s") %
                      (version, engine))
            raise


@six.add_metaclass(abc.ABCMeta)
class ModelsMigrationsSync(object):
    """A helper class for comparison of DB migration scripts and models.

    It's intended to be inherited by test cases in target projects. They have
    to provide implementations for methods used internally in the test (as
    we have no way to implement them here).

    test_model_sync() will run migration scripts for the engine provided and
    then compare the given metadata to the one reflected from the database.
    The difference between MODELS and MIGRATION scripts will be printed and
    the test will fail, if the difference is not empty.

    Method include_object() can be overriden to exclude some tables from
    comparison (e.g. migrate_repo).

    """

    @abc.abstractmethod
    def db_sync(self, engine):
        """Run migration scripts with the given engine instance.

        This method must be implemented in subclasses and run migration scripts
        for a DB the given engine is connected to.

        """

    @abc.abstractmethod
    def get_engine(self):
        """Return the engine instance to be used when running tests.

        This method must be implemented in subclasses and return an engine
        instance to be used when running tests.

        """

    @abc.abstractmethod
    def get_metadata(self):
        """Return the metadata instance to be used for schema comparison.

        This method must be implemented in subclasses and return the metadata
        instance attached to the BASE model.

        """

    def include_object(self, object_, name, type_, reflected, compare_to):
        """Return True for objects, that should be compared.

        :param object_: a SchemaItem object such as a Table or Column object
        :param name: the name of the object
        :param type_: a string describing the type of object (e.g. "table")
        :param reflected: True if the given object was produced based on
                          table reflection, False if it's from a local
                          MetaData object
        :param compare_to: the object being compared against, if available,
                           else None

        """

        return True

    def compare_type(self, ctxt, insp_col, meta_col, insp_type, meta_type):
        """Return True if types are different, False if not.

        Return None to allow the default implementation to compare these types.

        :param ctxt: alembic MigrationContext instance
        :param insp_col: reflected column
        :param meta_col: column from model
        :param insp_type: reflected column type
        :param meta_type: column type from model

        """

        # some backends (e.g. mysql) don't provide native boolean type
        BOOLEAN_METADATA = (types.BOOLEAN, types.Boolean)
        BOOLEAN_SQL = BOOLEAN_METADATA + (types.INTEGER, types.Integer)

        if issubclass(type(meta_type), BOOLEAN_METADATA):
            return not issubclass(type(insp_type), BOOLEAN_SQL)

        return None  # tells alembic to use the default comparison method

    def compare_server_default(self, ctxt, ins_col, meta_col,
                               insp_def, meta_def, rendered_meta_def):
        """Compare default values between model and db table.

        Return True if the defaults are different, False if not, or None to
        allow the default implementation to compare these defaults.

        :param ctxt: alembic MigrationContext instance
        :param insp_col: reflected column
        :param meta_col: column from model
        :param insp_def: reflected column default value
        :param meta_def: column default value from model
        :param rendered_meta_def: rendered column default value (from model)

        """

        if (ctxt.dialect.name == 'mysql' and
                issubclass(type(meta_col.type), sqlalchemy.Boolean)):

            if meta_def is None or insp_def is None:
                return meta_def != insp_def

            return not (
                isinstance(meta_def.arg, expr.True_) and insp_def == "'1'" or
                isinstance(meta_def.arg, expr.False_) and insp_def == "'0'"
            )

        return None  # tells alembic to use the default comparison method

    def test_models_sync(self):
        # recent versions of sqlalchemy and alembic are needed for running of
        # this test, but we already have them in requirements
        sa_version = tuple(int(p) for p in sqlalchemy.__version__.split('.'))
        alembic_version = tuple(int(p) for p in alembic.__version__.split('.'))
        if not (sa_version > (0, 8, 3) and alembic_version > (0, 6, 2)):
            self.skipTest(
                _LE('sqlalchemy>=0.8.4 and alembic>=0.6.3 are required'
                    ' for running of this test.')
            )

        # run migration scripts
        self.db_sync(self.get_engine())

        # drop all tables after a test run
        def cleanup():
            meta = sqlalchemy.MetaData(bind=self.get_engine())
            meta.reflect()
            meta.drop_all()
            self.get_metadata().drop_all(bind=self.get_engine())
        self.addCleanup(cleanup)

        with self.get_engine().connect() as conn:
            opts = {
                'include_object': self.include_object,
                'compare_type': self.compare_type,
                'compare_server_default': self.compare_server_default,
            }
            mc = alembic.migration.MigrationContext.configure(conn, opts=opts)

            # compare schemas and fail with diff, if it's not empty
            diff = alembic.autogenerate.compare_metadata(mc,
                                                         self.get_metadata())
            if diff:
                msg = pprint.pformat(diff, indent=2, width=20)

                self.fail(
                    "Models and migration scripts aren't in sync:\n%s" % msg)
