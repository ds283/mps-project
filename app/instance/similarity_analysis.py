#
# Created by David Seery on 13/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

# Sentence-transformers model used for cross-cohort cosine similarity.
# Must be a standard SentenceTransformer model (not adapter-based).
# Supported options: all-mpnet-base-v2 (default), all-MiniLM-L6-v2
SIMILARITY_ST_MODEL = os.environ.get("SIMILARITY_ST_MODEL", "all-mpnet-base-v2")

# Context window size (tokens) for the Ollama model during chunk extraction.
OLLAMA_CHUNK_EXTRACTION_CONTEXT_SIZE = int(
    os.environ.get("OLLAMA_CHUNK_EXTRACTION_CONTEXT_SIZE", "18432")
)
