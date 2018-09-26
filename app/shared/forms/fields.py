#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from wtforms import widgets, SubmitField, SelectMultipleField
from wtforms_alchemy import QuerySelectMultipleField


class CheckboxSelectMultipleField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class CheckboxQuerySelectMultipleField(QuerySelectMultipleField):

    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class EditFormMixin():

    submit = SubmitField('Save changes')
