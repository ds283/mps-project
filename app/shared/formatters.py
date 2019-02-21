#
# Created by David Seery on 03/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import timedelta


_kb = 1024
_Mb = 1024*_kb
_Gb = 1024*_Mb
_Tb = 1024*_Gb

_minute = 60
_hour = 60*60
_day = 24*60*60
_week = 7*24*60*60


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

    if seconds > _week:
        weeks, seconds = divmod(seconds, _week)
        res = (res + ' ' if len(res) > 0 else '') + '{n:.0f}w'.format(n=weeks)
    if seconds > _day:
        days, seconds = divmod(seconds, _day)
        res = (res + ' ' if len(res) > 0 else '') + '{n:.0f}d'.format(n=days)
    if seconds > _hour:
        hours, seconds = divmod(seconds, _hour)
        res = (res + ' ' if len(res) > 0 else '') + '{n:.0f}h'.format(n=hours)
    if seconds > _minute:
        minutes, seconds = divmod(seconds, _minute)
        res = (res + ' ' if len(res) > 0 else '') + '{n:.0f}m'.format(n=minutes)

    return (res + ' ' if len(res) > 0 else '') + '{n:.3f}s'.format(n=seconds)


def format_readable_time(seconds):
    if isinstance(seconds, timedelta):
        seconds = seconds.days*_day + seconds.seconds

    negative = False
    if seconds < 0:
        negative = True
        seconds = abs(seconds)

    if seconds > _week:
        weeks, seconds = divmod(seconds, _week)
        pl = '' if weeks == 1 else 's'
        return '{neg}{weeks} week{pl}'.format(weeks=weeks, pl=pl, neg='-' if negative else '')

    if seconds > _day:
        days, seconds = divmod(seconds, _day)
        pl = '' if days == 1 else 's'
        return '{neg}{days} day{pl}'.format(days=days, pl=pl, neg='-' if negative else '')

    if seconds > _hour:
        hours, seconds = divmod(seconds, _hour)
        pl = '' if hours == 1 else 's'
        return '{neg}{hours} hour{pl}'.format(hours=hours, pl=pl, neg='-' if negative else '')

    if seconds > _minute:
        minutes, seconds = divmod(seconds, _minute)
        pl = '' if minutes == 1 else 's'
        return '{neg}{minutes} minute{pl}'.format(minutes=minutes, pl=pl, neg='-' if negative else '')

    pl = '' if seconds == 1 else 's'
    return '{neg}{seconds} second{pl}'.format(seconds=seconds, pl=pl, neg='-' if negative else '')
