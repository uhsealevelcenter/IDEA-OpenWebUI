"""
title: Auto-upload PDFs to PaperQA
description: When a user attaches PDFs in chat, copy them into ~/papers in the
  user's Open Terminal home so PaperQA (pqa_query.py) can index and answer over
  them, then fire a background index prebuild so the first query is fast.
author: Nemo
version: 1.1.1
requirements: httpx

NOTE: This file is kept here for version control alongside the PaperQA skill.
Open WebUI does NOT auto-load it from disk — Functions live in Open WebUI's
database. To use it, copy the contents into Admin Settings -> Functions -> +,
then enable it (globally or per-model) and set the valves.
"""

import inspect
import logging
from typing import Callable, List, Optional

import httpx
from pydantic import BaseModel, Field

from open_webui.models.files import Files
from open_webui.storage.provider import Storage

log = logging.getLogger(__name__)


class Filter:
    class Valves(BaseModel):
        enabled: bool = Field(default=True, description="Enable the auto-upload filter")
        open_terminal_url: str = Field(
            default="http://open-terminal:8000",
            description="Open Terminal base URL reachable from the Open WebUI backend",
        )
        api_key: str = Field(
            default="", description="OPEN_TERMINAL_API_KEY for the Open Terminal instance"
        )
        target_directory: str = Field(
            default="papers",
            description="Destination dir relative to the user's home (PaperQA reads ~/papers)",
        )
        prebuild_index: bool = Field(
            default=True,
            description="After upload, fire pqa_query.py --prebuild so the first query is fast",
        )
        prebuild_script: str = Field(
            default="/opt/paperqa/pqa_query.py",
            description="Path to the PaperQA query script inside Open Terminal",
        )
        remove_pdf_from_files: bool = Field(
            default=False,
            description="Drop PDFs from the message so Open WebUI's own RAG skips them",
        )

    def __init__(self):
        self.valves = self.Valves()
        # Remembers (user_id, file_id) already uploaded this process lifetime.
        self._seen: set = set()

    @staticmethod
    def _is_pdf(f: dict) -> bool:
        if f.get("type") == "application/pdf":
            return True
        name = f.get("name", "") or f.get("filename", "")
        if name.lower().endswith(".pdf"):
            return True
        nested = f.get("file", {}) or {}
        if (nested.get("meta", {}) or {}).get("content_type") == "application/pdf":
            return True
        return nested.get("filename", "").lower().endswith(".pdf")

    @staticmethod
    def _file_id(f: dict) -> Optional[str]:
        return f.get("id") or (f.get("file", {}) or {}).get("id")

    async def _emit(self, emitter, description, done=False):
        if emitter:
            await emitter({"type": "status", "data": {"description": description, "done": done}})

    async def _prebuild(self, client: httpx.AsyncClient, base: str, headers: dict) -> None:
        """Fire a non-blocking index prebuild via Open Terminal's /execute API."""
        try:
            await client.post(
                base + "/execute",
                headers=headers,
                json={"command": f"python {self.valves.prebuild_script} --prebuild"},
                # wait=0 -> return immediately; the build keeps running in the
                # Open Terminal background process tracker.
                params={"wait": 0},
            )
        except Exception:
            log.exception("Failed to trigger PaperQA index prebuild")

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable] = None,
    ) -> dict:
        if not self.valves.enabled:
            return body

        files = body.get("files", []) or []
        pdfs = [f for f in files if self._is_pdf(f)]
        if not pdfs:
            return body

        user_id = (__user__ or {}).get("id", "")
        if not user_id:
            log.warning("No __user__ id; cannot route upload to the right home")
            return body

        headers = {
            "Authorization": f"Bearer {self.valves.api_key}",
            "X-User-Id": str(user_id),
        }
        base = self.valves.open_terminal_url.rstrip("/")

        uploaded = 0
        async with httpx.AsyncClient(timeout=60) as client:
            for entry in pdfs:
                fid = self._file_id(entry)
                if not fid or (user_id, fid) in self._seen:
                    continue
                try:
                    # get_file_by_id is async in newer Open WebUI, sync in older.
                    record = Files.get_file_by_id(fid)
                    if inspect.isawaitable(record):
                        record = await record
                    if not record or not record.path:
                        continue
                    local_path = Storage.get_file(record.path)
                    filename = record.filename or f"{fid}.pdf"
                    with open(local_path, "rb") as fh:
                        content = fh.read()

                    await self._emit(__event_emitter__, f"Uploading {filename} to PaperQA…")
                    resp = await client.post(
                        base + "/files/upload",
                        params={"directory": self.valves.target_directory},
                        headers=headers,
                        files={"file": (filename, content, "application/pdf")},
                    )
                    resp.raise_for_status()
                    self._seen.add((user_id, fid))
                    uploaded += 1
                except Exception:
                    log.exception("Failed to upload PDF %s to Open Terminal", fid)

            if uploaded and self.valves.prebuild_index:
                await self._emit(__event_emitter__, "Indexing new papers for PaperQA…")
                await self._prebuild(client, base, headers)

        if uploaded:
            await self._emit(
                __event_emitter__,
                f"Added {uploaded} PDF(s) to ~/{self.valves.target_directory} for PaperQA",
                done=True,
            )

        if self.valves.remove_pdf_from_files:
            pdf_ids = {self._file_id(p) for p in pdfs}
            body["files"] = [f for f in files if self._file_id(f) not in pdf_ids]
            meta = body.get("metadata", {})
            if meta.get("files") is not None:
                meta["files"] = [m for m in meta["files"] if self._file_id(m) not in pdf_ids]

        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        return body
