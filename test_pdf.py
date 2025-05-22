#
# Created by David Seery on 07/12/2021.
# Copyright (c) 2021 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import datetime
import re

import fitz
from dateutil.tz import tzutc, tzoffset

# PDF date parser borrowed from here: https://stackoverflow.com/questions/16503075/convert-creationtime-of-pdf-to-a-readable-format-in-python
pdf_date_pattern = re.compile(
    "".join(
        [
            r"(D:)?",
            r"(?P<year>\d\d\d\d)",
            r"(?P<month>\d\d)",
            r"(?P<day>\d\d)",
            r"(?P<hour>\d\d)",
            r"(?P<minute>\d\d)",
            r"(?P<second>\d\d)",
            r"(?P<tz_offset>[+-zZ])?",
            r"(?P<tz_hour>\d\d)?",
            r"'?(?P<tz_minute>\d\d)?'?",
        ]
    )
)


def transform_date(date_str):
    """
    Convert a pdf date such as "D:20120321183444+07'00'" into a usable datetime
    http://www.verypdf.com/pdfinfoeditor/pdf-date-format.htm
    (D:YYYYMMDDHHmmSSOHH'mm')
    :param date_str: pdf date string
    :return: datetime object
    """
    global pdf_date_pattern
    match = re.match(pdf_date_pattern, date_str)
    if match:
        date_info = match.groupdict()

        for k, v in date_info.items():  # transform values
            if v is None:
                pass
            elif k == "tz_offset":
                date_info[k] = v.lower()  # so we can treat Z as z
            elif k == "year" and len(v) == 5:
                date_info[k] = int("20" + v[3:])
            else:
                date_info[k] = int(v)

        if date_info["tz_offset"] in ("z", None):  # UTC
            date_info["tzinfo"] = tzutc()
        else:
            multiplier = 1 if date_info["tz_offset"] == "+" else -1
            date_info["tzinfo"] = tzoffset(None, multiplier * (3600 * date_info["tz_hour"] + 60 * date_info["tz_minute"]))

        for k in ("tz_offset", "tz_hour", "tz_minute"):  # no longer needed
            del date_info[k]

        return datetime.datetime(**date_info)


doc = fitz.open("AlexThesis.pdf")
num_pages = doc.page_count
metadata = doc.metadata

creation_date = transform_date(metadata["creationDate"])
modified_date = transform_date(metadata["modDate"])

coverpage_label = "MPhys Final Year Project cover page"
dyslexic_label = "SSU have flagged this student as having a specific learning difference. Before marking, please refer to the marking guidelines."

yellow = (255 / 255, 200 / 255, 69 / 255)
black = (0, 0, 0)
grey = (0.75, 0.75, 0.75)

# try to compute a word count
num_words = 0
for p in doc:
    str = p.get_text()
    words = str.split()
    num_words = num_words + len(words)

print("estimated total word count = {c}".format(c=num_words))

w, h = fitz.paper_size("A4")
page = doc.new_page(pno=0, width=w, height=h)

# redact
# for p in doc:
#     rlist = p.search_for('167035')
#     for r in rlist:
#         p.add_redact_annot(r, fill=grey, text='REDACTED', fontsize=11)
#
#     rlist = p.search_for('Alex Maraio')
#     for r in rlist:
#         p.add_redact_annot(r, fill=grey, text='REDACTED', fontsize=11)
#
#     p.apply_redactions()

ytop = 30
twidth = fitz.get_text_length(coverpage_label, fontname="Helvetica", fontsize=24)

x0 = (w - twidth) / 2
y0 = ytop + 24 + 4
p1 = fitz.Point(x0, y0)

rc = page.insert_text(p1, coverpage_label, color=black, fontname="Helvetica", fontsize=24)
ytop = ytop + 24 + 8 + 24

x0 = 25
y0 = ytop + 12 + 4
p2 = fitz.Point(x0, y0)

rc = page.insert_text(p2, "Number of pages: {n}".format(n=num_pages), color=black, fontname="Helvetica", fontsize=12)

x0 = int(w / 2)
p3 = fitz.Point(x0, y0)

rc = page.insert_text(p3, "Producer: {p}".format(p=metadata["producer"]), color=black, fontname="Helvetica", fontsize=12)
ytop = ytop + 12 + 8

x0 = 25
y0 = ytop + 12 + 4
p4 = fitz.Point(x0, y0)

rc = page.insert_text(p4, "Estimated word count: {n}".format(n=num_words), color=black, fontname="Helvetica", fontsize=12)

x0 = int(w / 2)
p5 = fitz.Point(x0, y0)

rc = page.insert_text(p5, "Format: {p}".format(p=metadata["format"]), color=black, fontname="Helvetica", fontsize=12)
ytop = ytop + 12 + 8

x0 = 25
y0 = ytop + 12 + 4
p6 = fitz.Point(x0, y0)

rc = page.insert_text(
    p6, "Created at {date}".format(date=creation_date.strftime("%a %d %b %Y %H:%M:%S")), color=black, fontname="Helvetica", fontsize=12
)

x0 = int(w / 2)
p7 = fitz.Point(x0, y0)

rc = page.insert_text(
    p7, "Last modified: {date}".format(date=modified_date.strftime("%a %d %b %Y %H:%M:%S")), color=black, fontname="Helvetica", fontsize=12
)
ytop = ytop + 12 + 8

xmargin = 100

rwidth = w - 2 * xmargin
rheight = 4 + 3 * 24 + 4

x0 = xmargin
y0 = ytop + 24

r1 = fitz.Rect(x0, y0, x0 + rwidth, y0 + rheight)

shape = page.new_shape()
shape.draw_rect(r1)
shape.finish(color=yellow, fill=yellow, width=0.3)

rc = shape.insert_textbox(r1, dyslexic_label, color=black, fontname="Helvetica", align=fitz.TEXT_ALIGN_CENTER, fontsize=18)

shape.commit()
doc.save("TestOutput.pdf")
