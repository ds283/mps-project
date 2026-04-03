#
# Created by David Seery on 03/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

# Base URL for the Ollama REST API
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# Model identifier to use for language analysis LLM submission
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:32b")
# OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:70b")
