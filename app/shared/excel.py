#
# Created by David Seery on 01/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


def _normalize_excel_sheet_name(name: str) -> str:
    if len(name) > 31:
        name = name[:31]

    name = name.replace("[", "(")
    name = name.replace("]", ")")
    name = name.replace(":", "-")
    name = name.replace("*", "-")
    name = name.replace("?", "-")
    name = name.replace("/", "-")

    return name
