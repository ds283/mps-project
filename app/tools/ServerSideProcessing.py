#
# Created by David Seery on 14/07/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import functools
import json
from collections.abc import Iterable

from flask import jsonify
from sqlalchemy.sql import collate, or_

from ..shared.utils import get_count


class ServerSideBase:
    """
    ServerSideBase provides common services for server side handler implementation classes.
    This includes parsing the DataTables request.
    """

    def __init__(self, request, query):
        """
        :param request: Flask 'request' instance, needs to be parsed to extract DataTables parameters
        """
        request_data = json.loads(request.values.get("args"))

        self._request_draw = None
        self._fail = False

        # extract parameters from the request
        try:
            # 'draw' parameter is a serial number
            self._request_draw = int(request_data['draw'])

            # first record to return
            self._request_start = int(request_data['start'])

            # number of records to return
            self._request_length = int(request_data['length'])

            # filter to apply
            self._request_filter = str(request_data['search']['value'])

            # array of column data supplied by front end
            self._request_columns = request_data['columns']

            # sort order to apply
            self._request_order = request_data['order']

        # if failed to look up, log an error
        except KeyError:

            self._fail = True
            self._fail_msg = 'The server could not interpret the AJAX payload from the website front-end'
            return

        # start with base query
        self._query = query

        # determine number of records available in base query alone
        self._number_total_rows = get_count(self._query)


class ServerSideSQLHandler(ServerSideBase):
    """
    ServerSideSQLHandler is a context manager for handling server side processing requests from
    client-side DataTables. It accepts a base query representing the total number of rows in the
    table, and then manipulates this query to pull out the rows required by the current DataTables
    pagination, sort and search values. The query is executed to build a JSON payload of row data.
    The point here is that we avoid reading more rows from the database than is necessary,
    but searching and sorting of rows is limited to what can be achieved using SQL.
    """

    def __init__(self, request, query, data):
        """
        :param request: Flask 'request' instance, needs to be parsed to extract DataTables parameters
        :param query: base query defining the set of records we consider (i.e. rows of the table)
        :param data: dictionary specifying columns to query and sort
        """
        # invoke superclass constructor
        super().__init__(request, query)

        # take a copy of the specified column data
        self._data = data

        # was a filter supplied? if so, then we should use it to restrict the base query
        if hasattr(self, '_request_filter') and self._request_filter is not None and len(self._request_filter) > 0:
            # filter_columns will contain a list of SQL conditions, one for each column that can be searched;
            # notice that DataTables mandates that a query is applied against *all* searchable columns
            # https://datatables.net/manual/server-side
            filter_columns = []

            # iterate through user-specified column data; if a column is marked as searchable,
            # then construct a filter for it.
            # Eventually, we will apply the logical-or of all these filters to the base query.
            for item_data in self._data.values():
                # is this column searchable?
                if 'search' in item_data:
                    # extract a column specification; this tells us which column (or possibly collection of columns)
                    # we should be applying the filter to
                    search_col = item_data['search']

                    # build SQLAlchemy expression representing the search criterion; this may eventually
                    # have to be wrapped inside a sub-search for a collection, but we deal with that below
                    collation = None
                    if 'search_collation' in item_data:
                        collation = item_data['search_collation']

                    if collation:
                        search_expr = collate(search_col, collation).contains(self._request_filter)
                    else:
                        search_expr = search_col.contains(self._request_filter)

                    # build filtering expression; check whether we need to search inside a collection
                    if 'search_collection' in item_data:
                        collection = item_data['search_collection']
                        filter_expr = collection.any(search_expr)
                    else:
                        filter_expr = search_expr

                    if filter_expr is not None:
                        filter_columns.append(filter_expr)

            # append logical-or of all filter conditions to the base query
            i = len(filter_columns)
            if i == 1:
                self._query = self._query.filter(filter_columns[0])
            elif i > 1:
                self._query = self._query.filter(or_(x for x in filter_columns))

        # count number of records after applying the filter (if we did so)
        # this may be equal to the total number of records if there is no filtering
        self._number_filtered_rows = get_count(self._query)

        # was an ordering supplied? if so, then we should apply it to the base query
        if hasattr(self, '_request_order') and self._request_order is not None:
            for item in self._request_order:
                # col_id is an index into the _request_columns array
                col_id = int(item['column'])
                dir = str(item['dir'])

                col_name = str(self._request_columns[col_id]['data'])

                if col_name in self._data:
                    item_data = self._data[col_name]

                    if 'order' in item_data:
                        order_col = item_data['order']

                    if dir == 'asc':
                        if isinstance(order_col, Iterable):
                            self._query = self._query.order_by(*(x.asc() for x in order_col))
                        else:
                            self._query = self._query.order_by(order_col.asc())
                    else:
                        if isinstance(order_col, Iterable):
                            self._query = self._query.order_by(*(x.desc() for x in order_col))
                        else:
                            self._query = self._query.order_by(order_col.desc())

        # impose limit on number of records retrieved
        if self._request_length > 0:
            self._query = self._query.limit(self._request_length)

        self._query = self._query.offset(self._request_start)


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, exc_traceback):
        return


    def build_payload(self, row_formatter):
        if not self._fail:
            return jsonify({'draw': self._request_draw,
                            'recordsTotal': self._number_total_rows,
                            'recordsFiltered': self._number_filtered_rows,
                            'data': row_formatter(self._query.all())})
        else:
            return jsonify({'draw': self._request_draw,
                            'error': self._fail_msg})


def _map_row(row, data):
    """
    Takes a raw row and uses the column data to build a dictionary with filter/sort fields
    :param row:
    :param data:
    :return:
    """
    mapped_row = {'columns': {col: {property: (getter(row) if callable(getter) else getter)
                                    for property, getter in fields.items()}
                              for col, fields in data.items()},
                  'row': row}

    return mapped_row


def _filter_row(row, search_value):
    columns = row['columns']

    # iterate over column
    for properties in columns.values():
        if 'search' in properties:
            value = properties['search'].lower()

            if search_value in value:
                return True

    return False


def _compare_rows(ordering_data, row_A, row_B):
    row_A_columns = row_A['columns']
    row_B_columns = row_B['columns']

    for col, dir in ordering_data:
        dir_factor = +1 if dir == 'asc' else -1

        row_A_col_properties = row_A_columns[col]
        row_B_col_properties = row_B_columns[col]

        row_A_value = row_A_col_properties['order']
        row_B_value = row_B_col_properties['order']

        if not isinstance(row_A_value, Iterable):
            row_A_value = [row_A_value]

        if not isinstance(row_B_value, Iterable):
            row_B_value = [row_B_value]

        if len(row_A_value) != len(row_B_value):
            raise TypeError

        for a, b in zip(row_A_value, row_B_value):
            if a < b:
                return -1 * dir_factor

            if a > b:
                return +1 * dir_factor

    return 0


class ServerSideInMemoryHandler(ServerSideBase):
    """
    ServerSideInMemoryHandler is a context manager for handling server side processing requests from
    client-side DataTables. It accepts a base query representing the total number of rows in the table,
    but then reads these into memory. The corresponding list can be filtered and sorted to match the
    parameters of the DataTables request. This approach is suitable for handling filters that are
    difficult or impossible to execute purely within SQL
    """

    def __init__(self, request, query, data):
        """
        :param request: Flask 'request' instance, needs to be parsed to extract DataTables parameters
        :param query: base query defining the set of records we consider (i.e. rows of the table)
        :param data: dictionary specifying columns to query and sort
        """
        # invoke superclass constructor
        super().__init__(request, query)

        # take a copy of the specified column data
        self._data = data

        # pull in all rows
        self._raw_rows = query.all()

        # use these to build a list of dictionaries, with members corresponding to the filter/sort
        # values determined by the column data
        self._mapped_rows = [_map_row(row, data) for row in self._raw_rows]

        # was a filter supplied? if so, then use it to filter rows from self._mapped_rows
        if hasattr(self, '_request_filter') and self._request_filter is not None and len(self._request_filter) > 0:
            # convert search value to lower case; note it's guaranteed to be a str
            self._request_filter = self._request_filter.lower()
            self._filtered_rows = [row for row in self._mapped_rows if _filter_row(row, self._request_filter)]

        if not hasattr(self, '_filtered_column'):
            self._filtered_rows = self._mapped_rows

        self._number_filtered_rows = len(self._filtered_rows)

        # was an ordering supplied? if so, then we should apply it
        if hasattr(self, '_request_order') and self._request_order is not None:
            ordering_data = []
            for item in self._request_order:
                # col_id is an index into the _request_columns array
                col_id = int(item['column'])
                dir = str(item['dir'])

                col_name = str(self._request_columns[col_id]['data'])

                if col_name in self._data:
                    ordering_data.append((col_name, dir))

            self._ordered_rows = sorted(self._filtered_rows,
                                        key=functools.cmp_to_key(functools.partial(_compare_rows, ordering_data)))

        if not hasattr(self, '_ordered_rows'):
            self._ordered_rows = self._filtered_rows

        if self._request_start < self._number_filtered_rows:
            start = self._request_start
            end = self._request_start + self._request_length

            if end > self._number_filtered_rows:
                end = self._number_filtered_rows

            self._ordered_rows = self._ordered_rows[start:end]
        else:
            self._ordered_rows = []


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, exc_traceback):
        return


    def build_payload(self, row_formatter):
        if not self._fail:
            return jsonify({'draw': self._request_draw,
                            'recordsTotal': self._number_total_rows,
                            'recordsFiltered': self._number_filtered_rows,
                            'data': row_formatter(x['row'] for x in self._ordered_rows)})
        else:
            return jsonify({'draw': self._request_draw,
                            'error': self._fail_msg})
