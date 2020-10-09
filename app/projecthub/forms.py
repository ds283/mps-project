#
# Created by David Seery on 09/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask_security.forms import Form
from wtforms import SubmitField, StringField, TextAreaField, BooleanField, DateTimeField
from wtforms.validators import InputRequired, Length, Optional

from ..models import DEFAULT_STRING_LENGTH
from ..shared.forms.mixins import SaveChangesMixin

class FormattedArticleForm(Form):

    title = StringField('Article title',
                        validators=[InputRequired('Please enter a title for your article or news story'),
                                    Length(max=DEFAULT_STRING_LENGTH)])

    article = TextAreaField('Article', validators=[Optional()], render_kw={"rows": 10})

    published = BooleanField('Published', description='Select this option to make your article visible to other users')

    publication_timestamp = DateTimeField('Automatically publish at a specified time', format='%d/%m/%Y %H:%M',
                                          description='If you wish your article to be published automatically at '
                                                      'a specified time, enter it here. Leave blank to disable '
                                                      'automated publication.',
                                          validators=[Optional()])



class AddFormatterArticleForm(FormattedArticleForm):

    submit = SubmitField('Add new article')


class EditFormattedArticleForm(FormattedArticleForm, SaveChangesMixin):

    pass
