#
# Created by David Seery on 03/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


_kb = 1024
_Mb = 1024*_kb
_Gb = 1024*_Mb
_Tb = 1024*_Gb


def format_size(s):

    if s > _Tb:
        return "{x:.3g} Tb".format(x=float(s)/_Tb)

    if s > _Gb:
        return "{x:.3g} Gb".format(x=float(s)/_Gb)

    if s > _Mb:
        return "{x:.3g} Mb".format(x=float(s)/_Mb)

    if s > _kb:
        return "{x:.3g} kb".format(x=float(s) / _kb)

    return "{x:.3g} bytes".format(x=float(s))


def format_time(seconds):

    res = ''

    if seconds > 60*60*24:
        days, seconds = divmod(seconds, 60*60*24)
        res = (res + ' ' if len(res) > 0 else '') + '{n:.0f}d'.format(n=days)
    if seconds > 60*60:
        hours, seconds = divmod(seconds, 60*60)
        res = (res + ' ' if len(res) > 0 else '') + '{n:.0f}h'.format(n=hours)
    if seconds > 60:
        minutes, seconds = divmod(seconds, 60)
        res = (res + ' ' if len(res) > 0 else '') + '{n:.0f}m'.format(n=minutes)

    return (res + ' ' if len(res) > 0 else '') + '{n:.3f}s'.format(n=seconds)