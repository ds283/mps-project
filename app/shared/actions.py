#
# Created by David Seery on 02/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template

import re


def render_project(data, desc, form=None, text=None, url=None):

    # build list of keywords
    keywords = [ kw.strip() for kw in re.split("[;,]", data.keywords) ]

    # without the sel variable, won't render any of the student-specific items
    return render_template('student/show_project.html', title=data.name, project=data, desc=desc, keywords=keywords,
                           form=form, text=text, url=url)



def do_confirm(sel, project):

    if sel not in project.confirm_waiting:
        return False

    project.confirm_waiting.remove(sel)

    if sel not in project.confirmed_students:
        project.confirmed_students.append(sel)

    return True


def do_deconfirm(sel, project):

    if sel in project.confirmed_students:

        project.confirmed_students.remove(sel)
        return True

    return False


def do_deconfirm_to_pending(sel, project):

    if sel not in project.confirmed_students:
        return False

    project.confirmed_students.remove(sel)

    if sel not in project.confirm_waiting:
        project.confirm_waiting.append(sel)

    return True


def do_cancel_confirm(sel, project):

    if sel not in project.confirm_waiting:
        return False

    project.confirm_waiting.remove(sel)
    return True
