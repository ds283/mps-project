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
# OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
# OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:32b")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:70b")

# Context window size (tokens) for the Ollama model.
# 18432 has been confirmed to work reliably on the current hardware.
OLLAMA_CONTEXT_SIZE = int(os.environ.get("OLLAMA_CONTEXT_SIZE", "18432"))

# Batch size for submission of reports to the LLM pipeline for appraisal.
# For running on a desktop-scale Mac Studio, we can probably only process 1 at once.
OLLAMA_BATCH_SIZE = int(os.environ.get("OLLAMA_BATCH_SIZE", "1"))

# TCP connect timeout (seconds) when opening a connection to the Ollama server.
OLLAMA_CONNECT_TIMEOUT = int(os.environ.get("OLLAMA_CONNECT_TIMEOUT", "30"))

# Per-chunk read timeout (seconds) for streaming responses from Ollama.
# This is not a total-generation limit — it is the maximum allowed gap between
# consecutive streamed tokens. It primarily needs to cover time-to-first-token.
OLLAMA_STREAMING_READ_TIMEOUT = int(os.environ.get("OLLAMA_STREAMING_READ_TIMEOUT", "180"))
