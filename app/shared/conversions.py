#
# Created by David Seery on 10/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

def is_integer(s):

    if isinstance(s, int):
        return True, s

    if not isinstance(s, str):
        return False, None

    try:
        integer = int(s)
        return True, integer
    except ValueError:
        pass

    return False, None
