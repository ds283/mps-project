#
# Created by ds283 on 08/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283 <>
#

import pandas as pd

cols = pd.read_csv("latin1-columns.csv", header=0)

with open("latin1-fix-statements.sql", "w") as f:
    for index, col in cols.iterrows():
        type = col["DATA_TYPE"]

        if type == "text":
            f.write(f"ALTER TABLE {col['TABLE_NAME']} MODIFY {col['COLUMN_NAME']} text CHARACTER SET utf8 COLLATE utf8_bin;\n")

        elif type == "varchar":
            f.write(
                f"ALTER TABLE {col['TABLE_NAME']} MODIFY {col['COLUMN_NAME']} varchar({col['CHARACTER_MAXIMUM_LENGTH']}) CHARACTER SET utf8 COLLATE utf8_bin;\n"
            )
