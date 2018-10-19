#
# Created by David Seery on 08/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import SubmitField, TextAreaField

from ..shared.forms.mixins import SaveChangesMixin, ThemeMixin


class StudentFeedbackMixin():

    feedback = TextAreaField('Enter feedback for your supervisor', render_kw={'rows': 5},
                             description='Your feedback can be structured using Markdown, or use LaTeX formatting '
                                         'and mathematical markup. Preview by looking on your feedback page.')

    save_changes = SubmitField('Save changes')

    save_preview = SubmitField('Save changes and preview')


class StudentFeedbackForm(Form, StudentFeedbackMixin):

    pass


class StudentSettingsForm(Form, ThemeMixin, SaveChangesMixin):

    pass
