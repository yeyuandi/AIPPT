# -*- coding: utf-8 -*-
"""业务编排层（调用 chains，不含 Flask）。"""
from .deck_jobs import (
    list_job_summaries,
    merged_pptx_path,
    run_deck_template_step,
    run_outline_step,
    save_deck_outline_files,
    save_document_source,
    save_slide_html,
    start_export_pptx,
    start_slide_html_generation,
    wizard_restore_bundle,
)
from .job_store import (
    MAX_WIZARD_RESTORE_DOCUMENT_CHARS,
    create_job,
    read_meta,
    read_progress,
    resolve_job_dir,
    web_jobs_root,
    write_meta,
)
from .outline import cap_outline_pages, invoke_outline_chain, meta_llm_provider

__all__ = [
    "MAX_WIZARD_RESTORE_DOCUMENT_CHARS",
    "cap_outline_pages",
    "create_job",
    "invoke_outline_chain",
    "list_job_summaries",
    "merged_pptx_path",
    "meta_llm_provider",
    "read_meta",
    "read_progress",
    "resolve_job_dir",
    "run_deck_template_step",
    "run_outline_step",
    "save_deck_outline_files",
    "save_document_source",
    "save_slide_html",
    "start_export_pptx",
    "start_slide_html_generation",
    "web_jobs_root",
    "wizard_restore_bundle",
    "write_meta",
]
