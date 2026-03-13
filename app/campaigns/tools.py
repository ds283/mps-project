#
# Created by David Seery on 03/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from flask_security import Form
from wtforms import BooleanField, SubmitField
from wtforms.validators import InputRequired
from wtforms_alchemy import QuerySelectMultipleField

from app.models import FacultyData, ProjectClass, ProjectTagGroup, Project, ProjectTag
from app.shared.sqlalchemy import get_count

from ..database import db


def check_2026_ATAS(fd: FacultyData):
    projects = []

    _TARGET_GROUP_LABEL = "Final Year Project labels"
    tag_group: ProjectTagGroup = (
        db.session.query(ProjectTagGroup)
        .filter(ProjectTagGroup.name == _TARGET_GROUP_LABEL)
        .first()
    )

    class InputForm(Form):
        submit = SubmitField("Continue")

    if tag_group is None:
        raise RuntimeError(f'Could not find tag group "{_TARGET_GROUP_LABEL}"')

    def query_factory():
        return db.session.query(ProjectTag).filter(ProjectTag.group_id == tag_group.id)

    def get_label(tag: ProjectTag):
        return tag.name

    def add_project(project: Project):
        projects.append(project)

        setattr(
            InputForm,
            f"project_{project.id}_ATAS",
            BooleanField(
                "This project is not suitable for ATAS-restricted students",
                default=False,
            ),
        )
        setattr(
            InputForm,
            f"project_{project.id}_tags",
            QuerySelectMultipleField(
                "Assign labels for this project",
                query_factory=query_factory,
                get_label=get_label,
                validators=[InputRequired(message="Please apply at least one tag")],
            ),
        )

    for project in fd.projects.filter(
            Project.active.is_(True),
    ):
        if any([p.tenant.in_2026_ATAS_campaign for p in project.project_classes]):
            if project.ATAS_restricted is None:
                add_project(project)
                continue

            for pclass in project.project_classes:
                pclass: ProjectClass

                if tag_group in pclass.force_tag_groups:
                    query = project.tags.filter(ProjectTagGroup.id == tag_group.id)
                    count = get_count(query)
                    if count == 0:
                        add_project(project)
                        continue

    return {
        "projects": projects,
        "form": InputForm,
    }
