from __future__ import annotations

import ctypes
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class PhoenixSdError(RuntimeError):
    """Erro devolvido pela bridge nativa Phoenix Diffusion."""


class _LoadConfig(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("diffusion_model_path", ctypes.c_char_p),
        ("clip_l_path", ctypes.c_char_p),
        ("clip_g_path", ctypes.c_char_p),
        ("t5xxl_path", ctypes.c_char_p),
        ("vae_path", ctypes.c_char_p),
        ("taesd_path", ctypes.c_char_p),
        ("backend", ctypes.c_char_p),
        ("params_backend", ctypes.c_char_p),
        ("max_vram", ctypes.c_char_p),
        ("split_mode", ctypes.c_char_p),
        ("model_args", ctypes.c_char_p),
        ("n_threads", ctypes.c_int32),
        ("auto_fit", ctypes.c_int32),
        ("stream_layers", ctypes.c_int32),
        ("eager_load", ctypes.c_int32),
        ("enable_mmap", ctypes.c_int32),
        ("diffusion_flash_attn", ctypes.c_int32),
        ("diffusion_conv_direct", ctypes.c_int32),
        ("vae_conv_direct", ctypes.c_int32),
        ("llm_path", ctypes.c_char_p),
        ("vae_format", ctypes.c_int32),
    ]


class _GenerateConfig(ctypes.Structure):
    _fields_ = [
        ("prompt", ctypes.c_char_p),
        ("negative_prompt", ctypes.c_char_p),
        ("sampler", ctypes.c_char_p),
        ("scheduler", ctypes.c_char_p),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("steps", ctypes.c_int32),
        ("cfg_scale", ctypes.c_float),
        ("distilled_guidance", ctypes.c_float),
        ("seed", ctypes.c_int64),
        ("batch_count", ctypes.c_int32),
        ("clip_skip", ctypes.c_int32),
        ("vae_tiling", ctypes.c_int32),
        ("vae_tile_size_x", ctypes.c_int32),
        ("vae_tile_size_y", ctypes.c_int32),
        ("vae_target_overlap", ctypes.c_float),
    ]


class _Image(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("channels", ctypes.c_uint32),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
        ("data_size", ctypes.c_size_t),
    ]


def _b(value: Optional[str]) -> Optional[bytes]:
    if not value:
        return None
    return os.fspath(value).encode("utf-8")


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def write_png(
    path: str | os.PathLike[str],
    width: int,
    height: int,
    channels: int,
    pixels: bytes,
) -> None:
    """Grava RGB/RGBA/grayscale 8-bit sem depender de Pillow."""
    if channels not in (1, 3, 4):
        raise ValueError(f"Quantidade de canais PNG não suportada: {channels}")
    expected = width * height * channels
    if len(pixels) != expected:
        raise ValueError(f"Buffer de pixels inválido: esperado {expected}, recebido {len(pixels)}")

    color_type = {1: 0, 3: 2, 4: 6}[channels]
    stride = width * channels
    scanlines = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(scanlines, 6))
        + _png_chunk(b"IEND", b"")
    )
    Path(path).write_bytes(data)


@dataclass(slots=True)
class ModelConfig:
    model_path: Optional[str] = None
    diffusion_model_path: Optional[str] = None
    clip_l_path: Optional[str] = None
    clip_g_path: Optional[str] = None
    t5xxl_path: Optional[str] = None
    vae_path: Optional[str] = None
    taesd_path: Optional[str] = None
    backend: Optional[str] = None
    params_backend: Optional[str] = None
    max_vram: Optional[str] = None
    split_mode: Optional[str] = None
    model_args: Optional[str] = None
    n_threads: int = -1
    auto_fit: bool = False
    stream_layers: bool = False
    eager_load: bool = False
    enable_mmap: bool = True
    diffusion_flash_attn: bool = False
    diffusion_conv_direct: bool = False
    vae_conv_direct: bool = False
    llm_path: Optional[str] = None
    vae_format: int = -1


@dataclass(slots=True)
class GenerationConfig:
    prompt: str
    negative_prompt: str = ""
    sampler: str = ""
    scheduler: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    distilled_guidance: float = -1.0
    seed: int = 42
    batch_count: int = 1
    clip_skip: int = -1
    vae_tiling: bool = False
    vae_tile_size_x: int = 0
    vae_tile_size_y: int = 0
    vae_target_overlap: float = 0.0


@dataclass(slots=True)
class GeneratedImage:
    width: int
    height: int
    channels: int
    pixels: bytes

    def save_png(self, path: str | os.PathLike[str]) -> None:
        write_png(path, self.width, self.height, self.channels, self.pixels)


class PhoenixSdNative:
    """Binding ctypes direto: sem CLI, servidor HTTP ou subprocesso."""

    def __init__(self, library_path: str | os.PathLike[str]):
        self.library_path = Path(library_path)
        if not self.library_path.is_file():
            raise FileNotFoundError(self.library_path)
        self._dll = ctypes.CDLL(str(self.library_path))
        self._configure_abi()
        self._handle = self._dll.phx_sd_create()
        if not self._handle:
            raise PhoenixSdError("phx_sd_create retornou ponteiro nulo")
        self._closed = False

    def _configure_abi(self) -> None:
        dll = self._dll
        dll.phx_sd_create.restype = ctypes.c_void_p
        dll.phx_sd_destroy.argtypes = [ctypes.c_void_p]
        dll.phx_sd_load_model.argtypes = [ctypes.c_void_p, ctypes.POINTER(_LoadConfig)]
        dll.phx_sd_load_model.restype = ctypes.c_int32
        dll.phx_sd_is_loaded.argtypes = [ctypes.c_void_p]
        dll.phx_sd_is_loaded.restype = ctypes.c_int32
        dll.phx_sd_unload_model.argtypes = [ctypes.c_void_p]
        dll.phx_sd_generate.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GenerateConfig), ctypes.POINTER(_Image)]
        dll.phx_sd_generate.restype = ctypes.c_int32
        dll.phx_sd_free_image.argtypes = [ctypes.POINTER(_Image)]
        dll.phx_sd_cancel.argtypes = [ctypes.c_void_p]
        dll.phx_sd_last_error.argtypes = [ctypes.c_void_p]
        dll.phx_sd_last_error.restype = ctypes.c_char_p
        dll.phx_sd_bridge_version.restype = ctypes.c_char_p
        dll.phx_sd_system_info.restype = ctypes.c_char_p
        dll.phx_sd_physical_cores.restype = ctypes.c_int32

    def _error(self) -> str:
        raw = self._dll.phx_sd_last_error(self._handle)
        return raw.decode("utf-8", "replace") if raw else "erro nativo desconhecido"

    @property
    def version(self) -> str:
        raw = self._dll.phx_sd_bridge_version()
        return raw.decode("utf-8", "replace") if raw else ""

    @property
    def system_info(self) -> str:
        raw = self._dll.phx_sd_system_info()
        return raw.decode("utf-8", "replace") if raw else ""

    @property
    def physical_cores(self) -> int:
        return int(self._dll.phx_sd_physical_cores())

    @property
    def is_loaded(self) -> bool:
        return bool(self._dll.phx_sd_is_loaded(self._handle))

    def load_model(self, cfg: ModelConfig) -> None:
        native = _LoadConfig(
            _b(cfg.model_path), _b(cfg.diffusion_model_path), _b(cfg.clip_l_path),
            _b(cfg.clip_g_path), _b(cfg.t5xxl_path), _b(cfg.vae_path),
            _b(cfg.taesd_path), _b(cfg.backend), _b(cfg.params_backend),
            _b(cfg.max_vram), _b(cfg.split_mode), _b(cfg.model_args),
            cfg.n_threads, int(cfg.auto_fit), int(cfg.stream_layers),
            int(cfg.eager_load), int(cfg.enable_mmap), int(cfg.diffusion_flash_attn),
            int(cfg.diffusion_conv_direct), int(cfg.vae_conv_direct),
            _b(cfg.llm_path), int(cfg.vae_format),
        )
        if not self._dll.phx_sd_load_model(self._handle, ctypes.byref(native)):
            raise PhoenixSdError(self._error())

    def unload_model(self) -> None:
        self._dll.phx_sd_unload_model(self._handle)

    def cancel(self) -> None:
        self._dll.phx_sd_cancel(self._handle)

    def generate(self, cfg: GenerationConfig) -> GeneratedImage:
        native = _GenerateConfig(
            _b(cfg.prompt), _b(cfg.negative_prompt), _b(cfg.sampler), _b(cfg.scheduler),
            cfg.width, cfg.height, cfg.steps, cfg.cfg_scale, cfg.distilled_guidance,
            cfg.seed, cfg.batch_count, cfg.clip_skip, int(cfg.vae_tiling),
            cfg.vae_tile_size_x, cfg.vae_tile_size_y, cfg.vae_target_overlap,
        )
        output = _Image()
        if not self._dll.phx_sd_generate(self._handle, ctypes.byref(native), ctypes.byref(output)):
            raise PhoenixSdError(self._error())
        try:
            pixels = ctypes.string_at(output.data, output.data_size)
            return GeneratedImage(int(output.width), int(output.height), int(output.channels), pixels)
        finally:
            self._dll.phx_sd_free_image(ctypes.byref(output))

    def close(self) -> None:
        if not self._closed:
            self._dll.phx_sd_destroy(self._handle)
            self._closed = True
            self._handle = None

    def __enter__(self) -> "PhoenixSdNative":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
