#
# Created by David Seery on 15/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from colour import Color


def get_text_colour(bg_colour):

    # assume bg_colour is string instance
    bg = Color(bg_colour)

    # compute perceived luminance
    a = 1 - (0.299 * bg.red + 0.587 * bg.green + 0.114 * bg.blue)

    if a < 0.5:
        return Color(rgb=(0,0,0)).hex_l

    return Color(rgb=(1,1,1)).hex_l
