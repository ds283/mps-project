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
    """
    Determine whether a supplied quantity 's' can be interpreted as an integer
    :param s: quantity to inspect
    :return: flag, value: flag is True/False depending whether s can be interpreted an integer;
    value is None if it cannot, otherwise the value of the determined integer
    """
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


def is_boolean(s):
    """
    Determine whether a supplied quantity 's' can be interpreted as a boolean
    :param s: quantity to inspect
    :return: flag, value: flag is True/False depending whether s can be interpreted as boolean;
    value is None if it cannot, otherwise True/False as determined
    """
    if isinstance(s, bool):
        return True, s

    if isinstance(s, int):
        return True, bool(s)

    if isinstance(s, float):
        return True, bool(int(s))

    try:
        value = bool(int(s))
        return True, value
    except ValueError:
        pass

    return False, None
