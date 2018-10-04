from __future__ import with_statement
from alembic import context
from alembic.ddl.impl import _type_comparators
from sqlalchemy import engine_from_config, pool
from sqlalchemy.sql import sqltypes
from logging.config import fileConfig
import logging

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from flask import current_app
config.set_main_option('sqlalchemy.url',
                       current_app.config.get('SQLALCHEMY_DATABASE_URI'))
target_metadata = current_app.extensions['migrate'].db.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


_compare_attrs = {
    sqltypes._Binary: ('length', ),
    sqltypes.Date: (),
    sqltypes.DateTime: ('fsp', 'timezone'),
    sqltypes.Integer: ('display_width', 'unsigned', 'zerofill'),
    sqltypes.String: ('binary', 'charset', 'collation', 'length', 'unicode'),
}


def db_compare_type(context, inspected_column,
                    metadata_column, inspected_type, metadata_type):
    # return True if the types are different, False if not, or None
    # to allow the default implementation to compare these TYPES
    expected = metadata_column.type
    migrated = inspected_column.type

    # this extends the logic in alembic.ddl.impl.DefaultImpl.compare_type
    type_affinity = migrated._type_affinity
    compare_attrs = _compare_attrs.get(type_affinity, None)
    if compare_attrs is not None:
        if type(expected) != type(migrated):
            return True
        for attr in compare_attrs:
            if getattr(expected, attr, None) != getattr(migrated, attr, None):
                return True
        return False

    # fall back to limited alembic type comparison
    comparator = _type_comparators.get(type_affinity, None)
    if comparator is not None:
        return comparator(expected, migrated)
    raise AssertionError('Unsupported DB type comparison.')


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    engine = engine_from_config(config.get_section(config.config_ini_section),
                                prefix='sqlalchemy.',
                                poolclass=pool.NullPool)

    connection = engine.connect()
    context.configure(connection=connection,
                      target_metadata=target_metadata,
                      compare_type=db_compare_type,
                      process_revision_directives=process_revision_directives,
                      **current_app.extensions['migrate'].configure_args)

    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.close()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
