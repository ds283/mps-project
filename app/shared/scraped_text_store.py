#
# Created by David Seery on 01/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from flask import current_app
from pymongo import MongoClient, ASCENDING


def _get_collection():
    """
    Return a (MongoClient, Collection) pair configured from Flask app config.
    Caller is responsible for closing the client.
    Returns None if the required config keys are absent or empty.
    """
    url = current_app.config.get("LANGUAGE_ANALYSIS_MONGO_URL")
    db_name = current_app.config.get("LANGUAGE_ANALYSIS_DATABASE")
    collection_name = current_app.config.get("LANGUAGE_ANALYSIS_SCRAPED_TEXT_COLLECTION")

    if not url or not db_name or not collection_name:
        return None, None

    client = MongoClient(url)
    collection = client[db_name][collection_name]
    return client, collection


def store_scraped_text(
    record_id: int,
    asset_id: int,
    mimetype: str,
    raw_text: str,
    page_count: int,
) -> bool:
    """
    Upsert a scraped-text document for *record_id* into the MongoDB cache.

    Creates the document on first call; updates scraped_text, asset_id, mimetype,
    page_count, and updated_at on subsequent calls.  created_at is set only on
    initial insert.

    Returns True on success, False if MongoDB is unconfigured or unavailable.
    """
    client, collection = _get_collection()
    if collection is None:
        current_app.logger.warning(
            "scraped_text_store.store_scraped_text: MongoDB not configured — skipping cache write"
        )
        return False

    try:
        # Ensure unique index exists (idempotent).
        collection.create_index([("submission_record_id", ASCENDING)], unique=True)

        now = datetime.now()
        collection.update_one(
            {"submission_record_id": record_id},
            {
                "$set": {
                    "asset_id": asset_id,
                    "mimetype": mimetype,
                    "scraped_text": raw_text,
                    "page_count": page_count,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "submission_record_id": record_id,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        return True

    except Exception as exc:
        current_app.logger.warning(
            f"scraped_text_store.store_scraped_text: failed for record #{record_id}: {exc}"
        )
        return False

    finally:
        client.close()


def get_scraped_text(record_id: int) -> dict | None:
    """
    Retrieve the cached scraped-text document for *record_id*.

    Returns a plain dict with at least the keys ``scraped_text`` and ``page_count``,
    or None on cache miss or error.
    """
    client, collection = _get_collection()
    if collection is None:
        current_app.logger.warning(
            "scraped_text_store.get_scraped_text: MongoDB not configured — cache miss"
        )
        return None

    try:
        doc = collection.find_one(
            {"submission_record_id": record_id},
            projection={"_id": False},
        )
        return doc

    except Exception as exc:
        current_app.logger.warning(
            f"scraped_text_store.get_scraped_text: failed for record #{record_id}: {exc}"
        )
        return None

    finally:
        client.close()


def delete_scraped_text(record_id: int) -> bool:
    """
    Delete the cached scraped-text document for *record_id*.

    Not called during normal pipeline operation (the cache is permanent), but
    exposed for admin cleanup and test teardown.

    Returns True on success (including no-op when document doesn't exist), False on error.
    """
    client, collection = _get_collection()
    if collection is None:
        current_app.logger.warning(
            "scraped_text_store.delete_scraped_text: MongoDB not configured — skipping"
        )
        return False

    try:
        collection.delete_one({"submission_record_id": record_id})
        return True

    except Exception as exc:
        current_app.logger.warning(
            f"scraped_text_store.delete_scraped_text: failed for record #{record_id}: {exc}"
        )
        return False

    finally:
        client.close()


def store_similarity_chunks(
    record_id: int,
    sections: dict,
    model_name: str,
    prompt_version: int,
    heading_style: str,
    top_level_heading_count: int,
) -> bool:
    """
    Upsert chunk extraction results into the scraped-text Mongo document.

    *sections* maps chunk_type → {"text": str, "present": bool}.
    Writes under the key "similarity_chunks" in the existing document.
    Creates the document if it does not yet exist.

    Returns True on success, False if MongoDB is unconfigured or unavailable.
    """
    client, collection = _get_collection()
    if collection is None:
        current_app.logger.warning(
            "scraped_text_store.store_similarity_chunks: MongoDB not configured — skipping"
        )
        return False

    try:
        now = datetime.now()
        collection.update_one(
            {"submission_record_id": record_id},
            {
                "$set": {
                    "similarity_chunks": {
                        "sections": sections,
                        "extracted_at": now,
                        "extraction_model": model_name,
                        "chunk_prompt_version": prompt_version,
                        "heading_style": heading_style,
                        "top_level_heading_count": top_level_heading_count,
                    }
                },
                "$setOnInsert": {
                    "submission_record_id": record_id,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        return True

    except Exception as exc:
        current_app.logger.warning(
            f"scraped_text_store.store_similarity_chunks: failed for record #{record_id}: {exc}"
        )
        return False

    finally:
        client.close()


def get_similarity_chunks(record_id: int) -> dict | None:
    """
    Retrieve the "similarity_chunks" subdocument for *record_id*.

    Returns the full subdocument (including sections, extracted_at, extraction_model,
    chunk_prompt_version, heading_style, top_level_heading_count, and optionally
    minhash_signatures and minhash_computed_at), or None on cache miss or absent key.
    """
    client, collection = _get_collection()
    if collection is None:
        current_app.logger.warning(
            "scraped_text_store.get_similarity_chunks: MongoDB not configured — cache miss"
        )
        return None

    try:
        doc = collection.find_one(
            {"submission_record_id": record_id},
            projection={"_id": False, "similarity_chunks": True},
        )
        if doc is None:
            return None
        return doc.get("similarity_chunks")

    except Exception as exc:
        current_app.logger.warning(
            f"scraped_text_store.get_similarity_chunks: failed for record #{record_id}: {exc}"
        )
        return None

    finally:
        client.close()


def store_minhash_signatures(record_id: int, signatures: dict) -> bool:
    """
    Upsert MinHash signatures into the "similarity_chunks" subdocument.

    *signatures* maps chunk_type → list[int] (MinHash hashvalues).
    Uses a targeted $set to avoid overwriting the rest of the subdocument.
    Also writes "similarity_chunks.minhash_computed_at".

    Returns True on success, False if MongoDB is unconfigured or unavailable.
    """
    client, collection = _get_collection()
    if collection is None:
        current_app.logger.warning(
            "scraped_text_store.store_minhash_signatures: MongoDB not configured — skipping"
        )
        return False

    try:
        now = datetime.now()
        collection.update_one(
            {"submission_record_id": record_id},
            {
                "$set": {
                    "similarity_chunks.minhash_signatures": signatures,
                    "similarity_chunks.minhash_computed_at": now,
                }
            },
        )
        return True

    except Exception as exc:
        current_app.logger.warning(
            f"scraped_text_store.store_minhash_signatures: failed for record #{record_id}: {exc}"
        )
        return False

    finally:
        client.close()
