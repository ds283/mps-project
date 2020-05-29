#
# Created by David Seery on 2018-12-06.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_uploads import UploadSet

solution_files = UploadSet(name='solutions', extensions=('lp', 'sol', 'mps'))
batch_user_files = UploadSet(name='batchuserlist', extensions=('csv'))
submitted_files = UploadSet(name='submissions', extensions=('pdf', 'doc', 'docx', 'odt', 'png'))
