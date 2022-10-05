#
# Created by David Seery on 2018-09-16.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from sqlalchemy import func, distinct, literal_column
from sqlalchemy.orm import lazyload


# taken from https://gist.github.com/hest/8798884
# see also https://datawookie.dev/blog/2021/01/sqlalchemy-efficient-counting/
def get_count(q):
    # col_one = literal_column("1")
    # count_q = q.statement.with_only_columns([func.count(col_one)]).order_by(None)
    # count = q.session.execute(count_q).scalar()
    #
    # return count if count is not None else 0
    return q.count()


# taken from https://stackoverflow.com/questions/28871406/how-to-clone-a-sqlalchemy-db-object-with-new-primary-key
def clone_model(model, **kwargs):
    """Clone an arbitrary sqlalchemy model object without its primary key values."""

    model_class = model.__class__

    # get tuple containing model class and its possible superclasses
    if hasattr(model_class, '__mro__'):
        class_list = model_class.__mro__
    else:
        class_list = model_class.mro()

    data = {}

    # loop through possible classes; for those that have a table attribute, unpack any fields corresponding
    # to columns of the table, except those that are tagged as primary key columns
    for c in class_list:
        if hasattr(c, '__table__'):
            table = c.__table__
            non_pk_columns = [k for k in table.columns.keys() if k not in table.primary_key]
            data = data | {c: getattr(model, c) for c in non_pk_columns}

    # merge any fields supplied in kwargs
    data.update(kwargs)

    # create a new instance of the model class using the fields/columns we have extracted
    clone = model_class(**data)

    return clone
