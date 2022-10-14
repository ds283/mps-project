#
# Created by David Seery on 14/10/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask_security.forms import Form
from wtforms_alchemy import QuerySelectField

from ..shared.forms.queries import GetPublishedProjectClasses


class PublicBrowserSelectorForm(Form):

    selector = QuerySelectField('Browse projects for', query_factory=GetPublishedProjectClasses, get_label='name')
