#
# Created by David Seery on 25/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# Kubernetes-style health and readiness probes via Flask-Healthz

HEALTHZ = {
    "live": "app.checks.liveness",
    "ready": "app.checks.readiness",
}
