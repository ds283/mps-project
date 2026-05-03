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

# Base URL for the llama-server REST API (default llama-server port is 8080).
# Falls back to the old OLLAMA_BASE_URL env var for backward compatibility.
LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", os.environ.get("OLLAMA_BASE_URL", "http://localhost:8080"))

# Model name stored for metadata and calibration matching.  With llama-server
# the model is embedded in the running process; this string is used only for
# provenance logging and TenantAICalibration.llm_model_name lookups.
# Falls back to OLLAMA_MODEL for backward compatibility.
# LLAMA_SERVER_MODEL = os.environ.get("LLAMA_SERVER_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1:8b"))
# LLAMA_SERVER_MODEL = os.environ.get("LLAMA_SERVER_MODEL", os.environ.get("OLLAMA_MODEL", "qwen2.5:32b"))
LLAMA_SERVER_MODEL = os.environ.get("LLAMA_SERVER_MODEL", os.environ.get("OLLAMA_MODEL", "llama3.1:70b"))

# Context window size (tokens) that llama-server was started with
# (--ctx-size flag).  Used for word-budget calculations only; the server must
# be launched with at least this value.  12288 has been confirmed to work
# reliably on the current hardware.
# Falls back to OLLAMA_CONTEXT_SIZE for backward compatibility.
LLAMA_SERVER_CTX_SIZE = int(os.environ.get("LLAMA_SERVER_CTX_SIZE", os.environ.get("OLLAMA_CONTEXT_SIZE", "12288")))

# Batch size for submission of reports to the LLM pipeline for appraisal.
# For running on a desktop-scale Mac Studio, we can probably only process 1 at once.
# Falls back to OLLAMA_BATCH_SIZE for backward compatibility.
LLAMA_SERVER_BATCH_SIZE = int(os.environ.get("LLAMA_SERVER_BATCH_SIZE", os.environ.get("OLLAMA_BATCH_SIZE", "1")))
