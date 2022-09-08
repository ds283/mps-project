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
from collections import Iterable

from flask import jsonify

from ..shared.utils import get_count

from sqlalchemy.sql import collate, or_


class ServerSideHandler:

    def __init__(self, request, query, data):
        """
        :param request: Flask 'request' instance
        :param query: base query defining the set of records we consider
        :param columns: dictionary specify columns to query and sort
        """

        request_data = json.loads(request.values.get("args"))

        self._draw = None
        self._fail = False

        try:
            self._draw = int(request_data['draw'])
            self._start = int(request_data['start'])
            self._length = int(request_data['length'])

            self._filter_value = str(request_data['search']['value'])

            self._columns = request_data['columns']
            self._order = request_data['order']
        except KeyError:
            self._fail = True
            self._fail_msg = 'The server could not interpret the AJAX payload from the website front-end'
            return

        self._query = query
        self._total_records = get_count(self._query)

        self._data = data

        # filter if being used
        if self._filter_value:
            filter_columns = []
            for item in self._data:
                item_data = self._data[item]

                if 'search' in item_data:
                   search_col = item_data['search']

                   if 'search_collation' in item_data:
                       collation = item_data['search_collation']
                       filter_columns.append(collate(search_col, collation).contains(self._filter_value))
                   else:
                       filter_columns.append(search_col.contains(self._filter_value))

            i = len(filter_columns)
            if i == 1:
                self._query = self._query.filter(filter_columns[0])
            elif i > 1:
                self._query = self._query.filter(or_(x for x in filter_columns))

        # count number of filtered records
        self._filtered_records = get_count(self._query)

        # impose specified ordering
        for item in self._order:
            # col_id is an index into the _columns array
            col_id = int(item['column'])
            dir = str(item['dir'])

            col_name = str(self._columns[col_id]['data'])

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
        if self._length > 0:
            self._query = self._query.limit(self._length)

        self._query = self._query.offset(self._start)


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, exc_traceback):
        return


    def build_payload(self, row_formatter):
        if not self._fail:
            return jsonify({'draw': self._draw,
                            'recordsTotal': self._total_records,
                            'recordsFiltered': self._filtered_records,
                            'data': row_formatter(self._query.all())})
        else:
            return jsonify({'draw': self._draw,
                            'error': self._fail_msg})
