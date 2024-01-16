#
# Created by David Seery on 12/12/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from wtforms_alchemy import GroupedQuerySelectMultipleField, QuerySelectMultipleField


class GroupedTagSelectField(GroupedQuerySelectMultipleField):
    def __init__(
        self, label=None, validators=None, query_factory=None, get_pk=None, get_label=None, get_group=None, blank_text="", default=None, **kwargs
    ):
        super().__init__(
            label=label,
            validators=validators,
            query_factory=query_factory,
            get_pk=get_pk,
            get_label=get_label,
            get_group=get_group,
            blank_text=blank_text,
            default=default,
            **kwargs
        )

    @property
    def data(self):
        formdata = self._formdata

        if formdata is not None:
            data = []
            for pk, obj in self._get_object_list():
                if not formdata:
                    break
                elif self.coerce(pk) in formdata:
                    formdata.remove(self.coerce(pk))
                    data.append(obj)

            # any primary keys (tag labels) that did not get moved out of formdata are the new ones we
            # wish to create, so aggregate these together with the matched set
            self.data = (data, formdata)

        return self._data

    @data.setter
    def data(self, value):
        if isinstance(value, tuple):
            self._data = value
        else:
            # assume we are just assigning the matched list, so the unmatched list should be set to empty
            self._data = (value, [])
        self._formdata = None

    def pre_validate(self, form):
        pass

    def process_data(self, value):
        try:
            # If value is None, don't coerce to a value
            self.data = (self.coerce(value), []) if value is not None else None
        except (ValueError, TypeError):
            self.data = None

    def iter_choices(self):
        """
        We should update how choices are iter to make sure that value from
        internal list or tuple should be selected.
        """
        data = self.data
        matched = data[0]

        for value, label in self.concrete_choices:
            yield (value, label, (self.coerce, [self.get_pk(obj) for obj in matched or []]))


class BasicTagSelectField(QuerySelectMultipleField):
    def __init__(self, label=None, validators=None, query_factory=None, get_pk=None, get_label=None, blank_text="", default=None, **kwargs):
        super().__init__(
            label=label,
            validators=validators,
            query_factory=query_factory,
            get_pk=get_pk,
            get_label=get_label,
            blank_text=blank_text,
            default=default,
            **kwargs
        )

    @property
    def data(self):
        formdata = self._formdata

        if formdata is not None:
            data = []
            for pk, obj in self._get_object_list():
                if not formdata:
                    break
                elif pk in formdata:
                    formdata.remove(pk)
                    data.append(obj)

            # any primary keys (tag labels) that did not get moved out of formdata are the new ones we
            # wish to create, so aggregate these together with the matched set
            self.data = (data, formdata)

        return self._data

    @data.setter
    def data(self, value):
        if isinstance(value, tuple):
            self._data = value
        else:
            # assume we are just assigning the matched list, so the unmatched list should be set to empty
            self._data = (value, [])
        self._formdata = None

    def pre_validate(self, form):
        pass

    def process_data(self, value):
        try:
            self.data = (value, []) if value is not None else None
        except (ValueError, TypeError):
            self.data = None

    def iter_choices(self):
        """
        We should update how choices are iter to make sure that value from
        internal list or tuple should be selected.
        """
        data = self.data
        matched = data[0]

        for pk, obj in self._get_object_list():
            yield (pk, self.get_label(obj), obj in matched)
