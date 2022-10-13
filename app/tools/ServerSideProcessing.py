#
# Created by David Seery on 14/07/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


import json
from collections.abc import Iterable

from flask import jsonify

from ..shared.utils import get_count

from sqlalchemy.sql import collate, or_


class ServerSideHandler:

    def __init__(self, request, query, data):
        """
        :param request: Flask 'request' instance
        :param query: base query defining the set of records we consider
        :param data: dictionary specifying columns to query and sort
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
        self._total_records = get_count(self._query)

        # take a copy of the specified column data
        self._data = data

        # was a filter supplied? if so, then we should use it to restrict the base query
        if self._request_filter:
            # filter_columns will contain a list of SQL conditions, one for each column that can be searched
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
        self._filtered_records = get_count(self._query)

        # was an ordering supplied? if so, then we should apply it to the base query
        for item in self._request_order:
            # col_id is an index into the _columns array
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
                            'recordsTotal': self._total_records,
                            'recordsFiltered': self._filtered_records,
                            'data': row_formatter(self._query.all())})
        else:
            return jsonify({'draw': self._request_draw,
                            'error': self._fail_msg})
