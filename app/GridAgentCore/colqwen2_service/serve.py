from __future__ import annotations

import base64
import io
import logging
import os
import threading
import time
from functools import lru_cache
from typing import Any

import numpy as np
import torch
from flask import Flask, jsonify, request
from PIL import Image
from transformers.utils.import_utils import is_flash_attn_2_available

from colpali_engine.models import ColQwen2, ColQwen2Processor


MODEL_NAME = os.getenv("COLQWEN2_MODEL_NAME", "vidore/colqwen2-v1.0")
RESPONSE_DTYPE = os.getenv("COLQWEN2_RESPONSE_DTYPE", "float16")
BATCH_LIMIT = int(os.getenv("COLQWEN2_MAX_BATCH_SIZE", "8"))
MAX_VISUAL_TOKENS = int(os.getenv("COLQWEN2_MAX_VISUAL_TOKENS", "384"))

app = Flask(__name__)
logging.basicConfig(level=os.getenv("COLQWEN2_LOG_LEVEL", "INFO"))
app.logger.setLevel(os.getenv("COLQWEN2_LOG_LEVEL", "INFO"))
_MODEL_LOAD_LOCK = threading.Lock()


def model_bundle() -> tuple[Any, Any, torch.device]:
    with _MODEL_LOAD_LOCK:
        return _cached_model_bundle()


@lru_cache(maxsize=1)
def _cached_model_bundle() -> tuple[Any, Any, torch.device]:
    started = time.perf_counter()
    app.logger.info("Loading ColQwen2 model=%s", MODEL_NAME)
    if torch.cuda.is_available():
        dtype = torch.bfloat16
        device_map = os.getenv("COLQWEN2_DEVICE_MAP", "cuda:0")
    else:
        dtype = torch.float32
        device_map = os.getenv("COLQWEN2_DEVICE_MAP", "cpu")
    model = ColQwen2.from_pretrained(
        MODEL_NAME,
        torch_dtype=dtype,
        device_map=device_map,
        attn_implementation="flash_attention_2" if is_flash_attn_2_available() else None,
    ).eval()
    processor_kwargs: dict[str, Any] = {}
    if MAX_VISUAL_TOKENS > 0:
        processor_kwargs["max_num_visual_tokens"] = MAX_VISUAL_TOKENS
    processor = ColQwen2Processor.from_pretrained(MODEL_NAME, **processor_kwargs)
    device = getattr(model, "device", None)
    if device is None:
        device = next(model.parameters()).device
    app.logger.info(
        "Loaded ColQwen2 in %.1fs device=%s dtype=%s max_visual_tokens=%s",
        time.perf_counter() - started,
        device,
        dtype,
        MAX_VISUAL_TOKENS,
    )
    return model, processor, torch.device(device)


@app.get("/ping")
def ping():
    model_bundle()
    return "ok", 200


@app.post("/invocations")
def invocations():
    started = time.perf_counter()
    try:
        payload = request.get_json(force=True, silent=False)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        task = payload.get("task")
        if task == "embed_images":
            images = [_decode_image(item) for item in payload.get("images", [])]
            _validate_batch(images)
            app.logger.info(
                "Embedding %s image(s): %s",
                len(images),
                [image.size for image in images],
            )
            embeddings = _embed_images(images)
        elif task == "embed_queries":
            queries = [str(item) for item in payload.get("queries", [])]
            _validate_batch(queries)
            app.logger.info("Embedding %s query(s)", len(queries))
            embeddings = _embed_queries(queries)
        else:
            return jsonify({"error": "task must be 'embed_images' or 'embed_queries'"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    app.logger.info("Completed %s in %.1fs", task, time.perf_counter() - started)
    return jsonify(
        {
            "model": MODEL_NAME,
            "response_format": "npy",
            "embeddings": [_pack_embedding(item) for item in embeddings],
        }
    )


def _validate_batch(items: list[Any]) -> None:
    if not items:
        raise ValueError("request batch must not be empty")
    if len(items) > BATCH_LIMIT:
        raise ValueError(f"request batch exceeds COLQWEN2_MAX_BATCH_SIZE={BATCH_LIMIT}")


def _embed_images(images: list[Image.Image]) -> list[np.ndarray]:
    model, processor, device = model_bundle()
    started = time.perf_counter()
    batch = processor.process_images(images).to(device)
    app.logger.info(
        "Processed %s image(s) in %.1fs grid=%s",
        len(images),
        time.perf_counter() - started,
        batch.get("image_grid_thw").tolist() if "image_grid_thw" in batch else None,
    )
    started = time.perf_counter()
    with torch.inference_mode():
        embeddings = model(**batch)
    app.logger.info("Ran image inference in %.1fs", time.perf_counter() - started)
    return [item.float().cpu().numpy() for item in torch.unbind(embeddings)]


def _embed_queries(queries: list[str]) -> list[np.ndarray]:
    model, processor, device = model_bundle()
    started = time.perf_counter()
    batch = processor.process_queries(queries).to(device)
    app.logger.info("Processed %s query(s) in %.1fs", len(queries), time.perf_counter() - started)
    started = time.perf_counter()
    with torch.inference_mode():
        embeddings = model(**batch)
    app.logger.info("Ran query inference in %.1fs", time.perf_counter() - started)
    return [item.float().cpu().numpy() for item in torch.unbind(embeddings)]


def _decode_image(item: Any) -> Image.Image:
    if isinstance(item, str):
        encoded = item
    elif isinstance(item, dict):
        encoded = item.get("data_base64") or item.get("image_base64") or ""
    else:
        encoded = ""
    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    image_bytes = base64.b64decode(encoded)
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def _pack_embedding(embedding: np.ndarray) -> dict[str, Any]:
    array = np.asarray(embedding).astype(RESPONSE_DTYPE)
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "data_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


if __name__ == "__main__":
    model_bundle()
    app.run(host="0.0.0.0", port=8080)
