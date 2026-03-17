#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# labels and keys for student 'level' field
student_level_choices = [(0, "UG"), (1, "PGT"), (2, "PGR")]

# labels and keys for 'year' field; it's not possible to join in Y1; treat students as
# joining in Y2
year_choices = [(2, "Year 2"), (3, "Year 3"), (4, "Year 4")]

# labels and keys for 'extent' field
extent_choices = [(1, "1 year"), (2, "2 years"), (3, "3 years")]

# labels and keys for the 'start year' field
start_year_choices = [(1, "Y1"), (2, "Y2"), (3, "Y3"), (4, "Y4")]

# labels and keys for 'academic titles' field
academic_titles = [
    (1, "Dr"),
    (2, "Professor"),
    (3, "Mr"),
    (4, "Ms"),
    (5, "Mrs"),
    (6, "Miss"),
    (7, "Mx"),
]

short_academic_titles = [
    (1, "Dr"),
    (2, "Prof"),
    (3, "Mr"),
    (4, "Ms"),
    (6, "Mrs"),
    (6, "Miss"),
    (7, "Mx"),
]

academic_titles_dict = dict(academic_titles)

short_academic_titles_dict = dict(short_academic_titles)

# labels and keys for years_history
matching_history_choices = [
    (1, "1 year"),
    (2, "2 years"),
    (3, "3 years"),
    (4, "4 years"),
    (5, "5 years"),
]

# PuLP solver choices
solver_choices = [
    (0, "PuLP-packaged CBC (amd64 only)"),
    (1, "CBC external command (amd64 or arm64)"),
    (2, "GLPK external command (amd64 or arm64)"),
    (3, "CPLEX external command (not available in cloud by default, requires license)"),
    (
        4,
        "Gurobi external command (not available in cloud by default, requires license)",
    ),
    (5, "SCIP external command  (not available in cloud by default, requires license)"),
]

# session types
session_choices = [(0, "Morning"), (1, "Afternoon")]

# semesters
semester_choices = [
    (0, "Autumn Semester"),
    (1, "Spring Semester"),
    (2, "Autumn & Spring teaching"),
    (3, "All-year teaching"),
]

# frequency of email summaries
email_freq_choices = [
    (1, "Every day"),
    (2, "Every two days"),
    (3, "Every three days"),
    (4, "Every four days"),
    (5, "Every five days"),
    (6, "Every six days"),
    (7, "Every seven days"),
]

# auto-enroll selectors
auto_enrol_year_choices = [
    (0, "The first year for which they are eligible"),
    (1, "Every year for which students are eligible"),
]
