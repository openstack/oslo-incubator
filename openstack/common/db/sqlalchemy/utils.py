# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010-2011 OpenStack Foundation.
# Copyright 2012 Justin Santa Barbara
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

# pylint: disable=W0611
import migrate  # NOQA
import sqlalchemy
from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy.engine import reflection
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import func
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy.sql.expression import literal_column
from sqlalchemy.sql.expression import UpdateBase
from sqlalchemy.sql import select
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy.types import NullType

from openstack.common.gettextutils import _  # noqa

from openstack.common import exception
from openstack.common import log as logging
from openstack.common import timeutils


LOG = logging.getLogger(__name__)

_SHADOW_TABLE_PREFIX = "shadow_"


class InvalidSortKey(Exception):
    message = _("Sort key supplied was not valid.")


# copy from glance/db/sqlalchemy/api.py
def paginate_query(query, model, limit, sort_keys, marker=None,
                   sort_dir=None, sort_dirs=None):
    """Returns a query with sorting / pagination criteria added.

    Pagination works by requiring a unique sort_key, specified by sort_keys.
    (If sort_keys is not unique, then we risk looping through values.)
    We use the last row in the previous page as the 'marker' for pagination.
    So we must return values that follow the passed marker in the order.
    With a single-valued sort_key, this would be easy: sort_key > X.
    With a compound-values sort_key, (k1, k2, k3) we must do this to repeat
    the lexicographical ordering:
    (k1 > X1) or (k1 == X1 && k2 > X2) or (k1 == X1 && k2 == X2 && k3 > X3)

    We also have to cope with different sort_directions.

    Typically, the id of the last row is used as the client-facing pagination
    marker, then the actual marker object must be fetched from the db and
    passed in to us as marker.

    :param query: the query object to which we should add paging/sorting
    :param model: the ORM model class
    :param limit: maximum number of items to return
    :param sort_keys: array of attributes by which results should be sorted
    :param marker: the last item of the previous page; we returns the next
                    results after this value.
    :param sort_dir: direction in which results should be sorted (asc, desc)
    :param sort_dirs: per-column array of sort_dirs, corresponding to sort_keys

    :rtype: sqlalchemy.orm.query.Query
    :return: The query with sorting/pagination added.
    """

    if 'id' not in sort_keys:
        # TODO(justinsb): If this ever gives a false-positive, check
        # the actual primary key, rather than assuming its id
        LOG.warn(_('Id not in sort_keys; is sort_keys unique?'))

    assert(not (sort_dir and sort_dirs))

    # Default the sort direction to ascending
    if sort_dirs is None and sort_dir is None:
        sort_dir = 'asc'

    # Ensure a per-column sort direction
    if sort_dirs is None:
        sort_dirs = [sort_dir for _sort_key in sort_keys]

    assert(len(sort_dirs) == len(sort_keys))

    # Add sorting
    for current_sort_key, current_sort_dir in zip(sort_keys, sort_dirs):
        sort_dir_func = {
            'asc': sqlalchemy.asc,
            'desc': sqlalchemy.desc,
        }[current_sort_dir]

        try:
            sort_key_attr = getattr(model, current_sort_key)
        except AttributeError:
            raise InvalidSortKey()
        query = query.order_by(sort_dir_func(sort_key_attr))

    # Add pagination
    if marker is not None:
        marker_values = []
        for sort_key in sort_keys:
            v = getattr(marker, sort_key)
            marker_values.append(v)

        # Build up an array of sort criteria as in the docstring
        criteria_list = []
        for i in range(0, len(sort_keys)):
            crit_attrs = []
            for j in range(0, i):
                model_attr = getattr(model, sort_keys[j])
                crit_attrs.append((model_attr == marker_values[j]))

            model_attr = getattr(model, sort_keys[i])
            if sort_dirs[i] == 'desc':
                crit_attrs.append((model_attr < marker_values[i]))
            elif sort_dirs[i] == 'asc':
                crit_attrs.append((model_attr > marker_values[i]))
            else:
                raise ValueError(_("Unknown sort direction, "
                                   "must be 'desc' or 'asc'"))

            criteria = sqlalchemy.sql.and_(*crit_attrs)
            criteria_list.append(criteria)

        f = sqlalchemy.sql.or_(*criteria_list)
        query = query.filter(f)

    if limit is not None:
        query = query.limit(limit)

    return query


def get_table(engine, name):
    """Returns an sqlalchemy table dynamically from db.

    Needed because the models don't work for us in migrations
    as models will be far out of sync with the current data.
    """
    metadata = MetaData()
    metadata.bind = engine
    return Table(name, metadata, autoload=True)


class InsertFromSelect(UpdateBase):
    """Form the base for `INSERT INTO table (SELECT ... )` statement."""
    def __init__(self, table, select):
        self.table = table
        self.select = select


@compiles(InsertFromSelect)
def visit_insert_from_select(element, compiler, **kw):
    """Form the `INSERT INTO table (SELECT ... )` statement."""
    return "INSERT INTO %s %s" % (
        compiler.process(element.table, asfrom=True),
        compiler.process(element.select))


def _get_not_supported_column(col_name_col_instance, column_name):
    try:
        column = col_name_col_instance[column_name]
    except KeyError:
        msg = _("Please specify column %s in col_name_col_instance "
                "param. It is required because column has unsupported "
                "type by sqlite).")
        raise exception.OpenstackException(message=msg % column_name)

    if not isinstance(column, Column):
        msg = _("col_name_col_instance param has wrong type of "
                "column instance for column %s It should be instance "
                "of sqlalchemy.Column.")
        raise exception.OpenstackException(message=msg % column_name)
    return column


def drop_old_duplicate_entries_from_table(migrate_engine, table_name,
                                          use_soft_delete, *uc_column_names):
    """Drop all old rows having the same values for columns in uc_columns.

    This method drop (or mark ad `deleted` if use_soft_delete is True) old
    duplicate rows form table with name `table_name`.

    :param migrate_engine:  Sqlalchemy engine
    :param table_name:      Table with duplicates
    :param use_soft_delete: If True - values will be marked as `deleted`,
                            if False - values will be removed from table
    :param uc_column_names: Unique constraint columns
    """
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table(table_name, meta, autoload=True)
    columns_for_group_by = [table.c[name] for name in uc_column_names]

    columns_for_select = [func.max(table.c.id)]
    columns_for_select.extend(columns_for_group_by)

    duplicated_rows_select = select(columns_for_select,
                                    group_by=columns_for_group_by,
                                    having=func.count(table.c.id) > 1)

    for row in migrate_engine.execute(duplicated_rows_select):
        # NOTE(boris-42): Do not remove row that has the biggest ID.
        delete_condition = table.c.id != row[0]
        is_none = None  # workaround for pyflakes
        delete_condition &= table.c.deleted_at == is_none
        for name in uc_column_names:
            delete_condition &= table.c[name] == row[name]

        rows_to_delete_select = select([table.c.id]).where(delete_condition)
        for row in migrate_engine.execute(rows_to_delete_select).fetchall():
            LOG.info(_("Deleting duplicated row with id: %(id)s from table: "
                       "%(table)s") % dict(id=row[0], table=table_name))

        if use_soft_delete:
            delete_statement = table.update().\
                where(delete_condition).\
                values({
                    'deleted': literal_column('id'),
                    'updated_at': literal_column('updated_at'),
                    'deleted_at': timeutils.utcnow()
                })
        else:
            delete_statement = table.delete().where(delete_condition)
        migrate_engine.execute(delete_statement)


def verify_shadow_table_definition_matches(migrate_engine, table_name):
    """Check shadow table and it's columns

    This method checks that table with ``table_name`` and corresponding shadow
    table have same columns.
    """
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table(table_name, meta, autoload=True)
    shadow_table = Table(_SHADOW_TABLE_PREFIX + table_name, meta,
                         autoload=True)

    columns = dict((c.name, c) for c in table.columns)
    shadow_columns = dict((c.name, c) for c in shadow_table.columns)

    if columns != shadow_columns:
        missed_columns = list(
            set(table.columns.keys()) - set(shadow_table.columns.keys())
        )
        if missed_columns:
            raise exception.OpenstackException(message=_(
                "Missing columns %(columns)s in shadow table %(shadow_table)s")
                % {'columns': ', '.join(missed_columns),
                   'shadow_table': shadow_table.name})

        extra_columns = list(
            set(shadow_table.columns.keys()) - set(table.columns.keys())
        )
        if extra_columns:
            raise exception.OpenstackException(message=_(
                "Extra columns %(columns)s in shadow table %(shadow_table)s")
                % {'columns': ', '.join(extra_columns),
                   'shadow_table': shadow_table.name}
            )

    wrong_type_columns = filter(
        lambda (n, c): not isinstance(shadow_columns[n].type, type(c.type)),
        columns.iteritems()
    )
    if wrong_type_columns:

        def _wrong_type_msg(name, column):
            msg = ("%(table)s.%(column)s and %(shadow_table)s.%(column)s: "
                   "%(c_type)s %(shadow_c_type)s "
                   ) % {'table': table.name, 'shadow_table': shadow_table.name,
                        'column': column, 'c_type': columns[name].type,
                        'shadow_c_type': shadow_columns[name].type}
            return msg

        raise exception.OpenstackException(message=_(
            "Different types in columns: %s")
            % ", ".join([_wrong_type_msg(n, c) for n, c in wrong_type_columns])
        )

    return True


def create_shadow_table(migrate_engine, table_name=None, table=None,
                        **col_name_col_instance):
    """Create shadow table for table `table_name`` or table instance ``table``

    This method create shadow table for table with name ``table_name`` or table
    instance ``table``.
    :param table_name: Autoload table with this name and create shadow table
    :param table: Autoloaded table, so just create corresponding shadow table.
    :param col_name_col_instance:   contains pair column_name=column_instance.
                            column_instance is instance of Column. These params
                            are required only for columns that have unsupported
                            types by sqlite. For example BigInteger.
    """
    meta = MetaData(bind=migrate_engine)

    if table_name is None and table is None:
        raise exception.OpenstackException(
            message=_("Specify `table_name` or `table` param"))
    if not (table_name is None or table is None):
        raise exception.OpenstackException(
            message=_("Specify only one param `table_name` `table`"))

    if table is None:
        table = Table(table_name, meta, autoload=True)

    columns = []
    for column in table.columns:
        if isinstance(column.type, NullType):
            new_column = _get_not_supported_column(col_name_col_instance,
                                                   column.name)
            columns.append(new_column)
        else:
            columns.append(column.copy())

    shadow_table_name = _SHADOW_TABLE_PREFIX + table.name
    shadow_table = Table(shadow_table_name, meta, *columns,
                         mysql_engine='InnoDB')
    try:
        shadow_table.create()
    except (OperationalError, ProgrammingError):
        LOG.info(repr(shadow_table))
        LOG.exception(_('Exception while creating table.'))
        raise exception.ShadowTableExists(name=shadow_table_name)
    except Exception:
        LOG.info(repr(shadow_table))
        LOG.exception(_('Exception while creating table.'))


def _get_default_deleted_value(table):
    if isinstance(table.c.id.type, Integer):
        return 0
    if isinstance(table.c.id.type, String):
        return ""
    raise exception.OpenstackException(
        message=_("Unsupported id columns type"))


def _restore_indexes_on_deleted_columns(migrate_engine, table_name, indexes):
    table = get_table(migrate_engine, table_name)

    insp = reflection.Inspector.from_engine(migrate_engine)
    real_indexes = insp.get_indexes(table_name)
    existing_index_names = dict(
        [(index['name'], index['column_names']) for index in real_indexes])

    # NOTE(boris-42): Restore indexes on `deleted` column
    for index in indexes:
        if 'deleted' not in index['column_names']:
            continue
        name = index['name']
        if name in existing_index_names:
            column_names = [table.c[c] for c in existing_index_names[name]]
            old_index = Index(name, *column_names, unique=index["unique"])
            old_index.drop(migrate_engine)

        column_names = [table.c[c] for c in index['column_names']]
        new_index = Index(index["name"], *column_names, unique=index["unique"])
        new_index.create(migrate_engine)


def change_deleted_column_type_to_boolean(migrate_engine, table_name,
                                          **col_name_col_instance):
    if migrate_engine.name == "sqlite":
        return _change_deleted_column_type_to_boolean_sqlite(
            migrate_engine, table_name, **col_name_col_instance)
    insp = reflection.Inspector.from_engine(migrate_engine)
    indexes = insp.get_indexes(table_name)

    table = get_table(migrate_engine, table_name)

    old_deleted = Column('old_deleted', Boolean, default=False)
    old_deleted.create(table, populate_default=False)

    table.update().\
        where(table.c.deleted == table.c.id).\
        values(old_deleted=True).\
        execute()

    table.c.deleted.drop()
    table.c.old_deleted.alter(name="deleted")

    _restore_indexes_on_deleted_columns(migrate_engine, table_name, indexes)


def _change_deleted_column_type_to_boolean_sqlite(migrate_engine, table_name,
                                                  **col_name_col_instance):
    insp = reflection.Inspector.from_engine(migrate_engine)
    table = get_table(migrate_engine, table_name)

    columns = []
    for column in table.columns:
        column_copy = None
        if column.name != "deleted":
            if isinstance(column.type, NullType):
                column_copy = _get_not_supported_column(col_name_col_instance,
                                                        column.name)
            else:
                column_copy = column.copy()
        else:
            column_copy = Column('deleted', Boolean, default=0)
        columns.append(column_copy)

    constraints = [constraint.copy() for constraint in table.constraints]

    meta = MetaData(bind=migrate_engine)
    new_table = Table(table_name + "__tmp__", meta,
                      *(columns + constraints))
    new_table.create()

    indexes = []
    for index in insp.get_indexes(table_name):
        column_names = [new_table.c[c] for c in index['column_names']]
        indexes.append(Index(index["name"], *column_names,
                             unique=index["unique"]))

    c_select = []
    for c in table.c:
        if c.name != "deleted":
            c_select.append(c)
        else:
            c_select.append(table.c.deleted == table.c.id)

    ins = InsertFromSelect(new_table, select(c_select))
    migrate_engine.execute(ins)

    table.drop()
    [index.create(migrate_engine) for index in indexes]

    new_table.rename(table_name)
    new_table.update().\
        where(new_table.c.deleted == new_table.c.id).\
        values(deleted=True).\
        execute()


def change_deleted_column_type_to_id_type(migrate_engine, table_name,
                                          **col_name_col_instance):
    if migrate_engine.name == "sqlite":
        return _change_deleted_column_type_to_id_type_sqlite(
            migrate_engine, table_name, **col_name_col_instance)
    insp = reflection.Inspector.from_engine(migrate_engine)
    indexes = insp.get_indexes(table_name)

    table = get_table(migrate_engine, table_name)

    new_deleted = Column('new_deleted', table.c.id.type,
                         default=_get_default_deleted_value(table))
    new_deleted.create(table, populate_default=True)

    deleted = True  # workaround for pyflakes
    table.update().\
        where(table.c.deleted == deleted).\
        values(new_deleted=table.c.id).\
        execute()
    table.c.deleted.drop()
    table.c.new_deleted.alter(name="deleted")

    _restore_indexes_on_deleted_columns(migrate_engine, table_name, indexes)


def _change_deleted_column_type_to_id_type_sqlite(migrate_engine, table_name,
                                                  **col_name_col_instance):
    # NOTE(boris-42): sqlaclhemy-migrate can't drop column with check
    #                 constraints in sqlite DB and our `deleted` column has
    #                 2 check constraints. So there is only one way to remove
    #                 these constraints:
    #                 1) Create new table with the same columns, constraints
    #                 and indexes. (except deleted column).
    #                 2) Copy all data from old to new table.
    #                 3) Drop old table.
    #                 4) Rename new table to old table name.
    insp = reflection.Inspector.from_engine(migrate_engine)
    meta = MetaData(bind=migrate_engine)
    table = Table(table_name, meta, autoload=True)
    default_deleted_value = _get_default_deleted_value(table)

    columns = []
    for column in table.columns:
        column_copy = None
        if column.name != "deleted":
            if isinstance(column.type, NullType):
                column_copy = _get_not_supported_column(col_name_col_instance,
                                                        column.name)
            else:
                column_copy = column.copy()
        else:
            column_copy = Column('deleted', table.c.id.type,
                                 default=default_deleted_value)
        columns.append(column_copy)

    def is_deleted_column_constraint(constraint):
        # NOTE(boris-42): There is no other way to check is CheckConstraint
        #                 associated with deleted column.
        if not isinstance(constraint, CheckConstraint):
            return False
        sqltext = str(constraint.sqltext)
        return (sqltext.endswith("deleted in (0, 1)") or
                sqltext.endswith("deleted IN (:deleted_1, :deleted_2)"))

    constraints = []
    for constraint in table.constraints:
        if not is_deleted_column_constraint(constraint):
            constraints.append(constraint.copy())

    new_table = Table(table_name + "__tmp__", meta,
                      *(columns + constraints))
    new_table.create()

    indexes = []
    for index in insp.get_indexes(table_name):
        column_names = [new_table.c[c] for c in index['column_names']]
        indexes.append(Index(index["name"], *column_names,
                             unique=index["unique"]))

    ins = InsertFromSelect(new_table, table.select())
    migrate_engine.execute(ins)

    table.drop()
    [index.create(migrate_engine) for index in indexes]

    new_table.rename(table_name)
    deleted = True  # workaround for pyflakes
    new_table.update().\
        where(new_table.c.deleted == deleted).\
        values(deleted=new_table.c.id).\
        execute()

    # NOTE(boris-42): Fix value of deleted column: False -> "" or 0.
    deleted = False  # workaround for pyflakes
    new_table.update().\
        where(new_table.c.deleted == deleted).\
        values(deleted=default_deleted_value).\
        execute()
