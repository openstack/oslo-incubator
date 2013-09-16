# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

"""Provision test environment for specific DB backends"""

import argparse
import os
import random
import string

import sqlalchemy


SQL_CONNECTION = os.getenv('OS_TEST_DBAPI_ADMIN_CONNECTION', 'sqlite://')


def _gen_credentials(*names):
    """Generate credentials."""
    auth_dict = {}
    for name in names:
        val = ''.join(random.choice(string.lowercase) for i in xrange(10))
        auth_dict[name] = val
    return auth_dict


def _get_engine(uri=SQL_CONNECTION):
    """Engine creation

    By default the uri is SQL_CONNECTION which is admin credentials.
    Call the function without arguments to get admin connection. Admin
    connection required to create temporary user and database for each
    particular test. Otherwise use existing connection to recreate connection
    to the temporary database.
    """
    return sqlalchemy.create_engine(uri, poolclass=sqlalchemy.pool.NullPool)


def _execute_sql(engine, sql, driver):
    """Initialize connection, execute sql query and close it."""
    with engine.connect() as conn:
        if driver == 'postgresql':
            conn.connection.set_isolation_level(0)
        for s in sql:
            conn.execute(s)


def create_database(engine):
    """Provide temporary user and database for each particular test."""
    driver = engine.name

    auth = _gen_credentials('database', 'user', 'passwd')

    sqls = {
        'mysql': [
            "drop database if exists %(database)s;",
            "grant all on %(database)s.* to '%(user)s'@'localhost'"
            " identified by '%(passwd)s';",
            "create database %(database)s;",
        ],
        'postgresql': [
            "drop database if exists %(database)s;",
            "drop user if exists %(user)s;",
            "create user %(user)s with password '%(passwd)s';",
            "create database %(database)s owner %(user)s;",
        ]
    }

    if driver == 'sqlite':
        return 'sqlite:////tmp/%s' % auth['database']

    try:
        sql = map(lambda x: x % auth, sqls[driver])
    except KeyError:
        raise ValueError('Unsupported RDBMS %s' % driver)

    _execute_sql(engine, sql, driver)

    params = auth.copy()
    params['backend'] = driver
    return "%(backend)s://%(user)s:%(passwd)s@localhost/%(database)s" % params


def drop_database(engine, current_uri):
    """Drop temporary database and user after each particular test."""
    engine = _get_engine(current_uri)
    admin_engine = _get_engine()
    driver = engine.name
    auth = {'database': engine.url.database, 'user': engine.url.username}

    if driver == 'sqlite':
        try:
            os.remove(auth['database'])
        except OSError:
            pass
        return

    sqls = {
        'mysql': [
            "drop database if exists %(database)s;",
            "drop user '%(user)s'@'localhost';",
        ],
        'postgresql': [
            "drop database if exists %(database)s;",
            "drop user if exists %(user)s;",
        ]
    }

    try:
        sql = map(lambda x: x % auth, sqls[driver])
    except KeyError:
        raise ValueError('Unsupported RDBMS %s' % driver)

    _execute_sql(admin_engine, sql, driver)


def main():
    """Controller to handle commands

    ::create: Create test user and database with random names.
    ::drop: Drop user and database created by previous command.
    """
    parser = argparse.ArgumentParser(
        description='Controller to handle database creation and dropping'
        ' commands.',
        epilog='Under normal circumstances is not used directly.'
        ' Used in .testr.conf to automate a test database creation'
        ' and dropping processes.')
    parser.add_argument(
        'command',
        choices=['create', 'drop'],
        help='Allowed two values:'
        '\n::create: create new test database and user at given backend.'
        '\n::drop: drop the database and the user created by the previous'
        ' command.')
    parser.add_argument(
        'inst',
        metavar='instance',
        nargs='+',
        help='Incoming data type varies depending on the command.'
        ' If it is createion of a databse expected an integer due to a number'
        ' of test databases to be created. If it is dropping of a database '
        'expected one or more databse dns string to drop it.')
    args = parser.parse_args()

    engine = _get_engine()
    command = args.command
    instances = args.inst

    if command == "create":
        for i in range(int(instances[0])):
            print(create_database(engine))
    elif command == "drop":
        for db in instances:
            drop_database(engine, db)


if __name__ == "__main__":
    main()
