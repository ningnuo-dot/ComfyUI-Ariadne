"""媒体助手：ComfyUI 张量/VIDEO 输入 → 本地文件；ffmpeg 裁剪与切点检测。

VIDEO 输入解析沿用本机 ComfyUI-Kie 基线的 get_stream_source() 模式（实测可用）。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from .seedance.ark_media import probe_video


def temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "ariadne_comfyui"
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_to_file(image) -> str:
    """ComfyUI IMAGE 张量 [B,H,W,C]（0-1 float，torch 或 numpy）→ PNG 临时文件。"""
    import numpy as np
    from PIL import Image

    if hasattr(image, "dim"):  # torch.Tensor
        image = image[0] if image.dim() == 4 else image
        array = (image.detach().cpu().numpy().clip(0, 1) * 255.0).round().astype(np.uint8)
    else:  # numpy [B,H,W,C] 或 [H,W,C]
        array = np.asarray(image)
        if array.ndim == 4:
            array = array[0]
        array = (array.clip(0, 1) * 255.0).round().astype(np.uint8)
    path = temp_dir() / f"ariadne-img-{uuid.uuid4().hex[:8]}.png"
    Image.fromarray(array).save(path)
    return str(path)


def images_to_files(images) -> list[str]:
    return [image_to_file(images[index]) for index in range(images.shape[0])]


def video_to_file(video) -> str:
    """ComfyUI VIDEO 输入 → 本地文件路径（流式来源落临时文件）。"""
    source = video.get_stream_source() if hasattr(video, "get_stream_source") else video
    if isinstance(source, (str, os.PathLike)):
        return str(source)
    if hasattr(source, "read"):
        path = temp_dir() / f"ariadne-video-{uuid.uuid4().hex[:8]}.mp4"
        position = source.tell() if hasattr(source, "tell") else None
        if hasattr(source, "seek"):
            source.seek(0)
        with open(path, "wb") as target:
            target.write(source.read())
        if position is not None and hasattr(source, "seek"):
            source.seek(position)
        return str(path)
    raise ValueError("不支持的 VIDEO 输入，请连接标准 ComfyUI VIDEO 输出。")


def audio_to_wav(audio) -> str:
    """ComfyUI AUDIO（waveform/sample_rate）→ WAV 临时文件。"""
    import io
    import wave

    import numpy as np
    import torch

    waveform = audio["waveform"]
    sample_rate = int(audio["sample_rate"])
    if waveform.dim() == 2:
        waveform = waveform.unsqueeze(0)
    samples = waveform[0].detach().cpu()
    if samples.dtype != torch.float32:
        samples = samples.float()
    samples = samples.clamp(-1.0, 1.0)
    pcm = (samples.numpy().T * 32767.0).round().astype(np.int16)
    path = temp_dir() / f"ariadne-audio-{uuid.uuid4().hex[:8]}.wav"
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(int(samples.shape[0]))
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return str(path)


def detect_cut_points(path: str, threshold: float = 0.3, max_points: int = 60) -> list[float]:
    """ffmpeg 场景切换检测：返回切点时刻列表（秒，不含 0）。用于分镜均摊裁剪。"""
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    points: list[float] = []
    for match in re.finditer(r"pts_time:([\d.]+)", result.stderr or ""):
        points.append(round(float(match.group(1)), 2))
        if len(points) >= max_points:
            break
    return points


def trim_video(path: str, ranges: list[list[float]], out_dir: str, base_name: str = "") -> str:
    """按保留区间（秒）裁剪视频：单段直接转码截取；多段 filter_complex concat 拼接。

    用重编码保证切点精确（参考视频计费按秒，误差直接变钱；流拷贝关键帧对齐误差 ±2s 不可接受）。
    返回输出文件路径。产物不含音轨会丢失音频参考——保留音频（aac）。
    """
    info = probe_video(path)
    duration = info["seconds"] or 0
    has_audio = False
    try:
        import av

        with av.open(path) as container:
            has_audio = len(container.streams.audio) > 0
    except Exception:
        has_audio = False
    ranges = [
        [max(0.0, float(start)), min(float(end), duration) if duration else float(end)]
        for start, end in ranges
        if float(end) > float(start)
    ]
    if not ranges:
        raise RuntimeError("裁剪区间为空：请至少保留一段大于 0 秒的内容。")
    stem = Path(base_name or path).stem
    output = Path(out_dir) / f"ariadne-trim-{int(duration)}s-{stem[:24]}-{uuid.uuid4().hex[:6]}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    if len(ranges) == 1:
        start, end = ranges[0]
        # -ss 做输入选项 + -t 输出选项（时长）：-to 与输入 -ss 组合的基准点有歧义，避免。
        command = [
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-i", path,
            "-t", f"{end - start:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-movflags", "+faststart", str(output),
        ]
    elif has_audio:
        inputs: list[str] = ["-i", path]
        filters = []
        for index, (start, end) in enumerate(ranges):
            filters.append(f"[0:v]trim={start:.3f}:{end:.3f},setpts=PTS-STARTPTS[v{index}]")
            filters.append(f"[0:a]atrim={start:.3f}:{end:.3f},asetpts=PTS-STARTPTS[a{index}]")
        video_labels = "".join(f"[v{i}]" for i in range(len(ranges)))
        audio_labels = "".join(f"[a{i}]" for i in range(len(ranges)))
        filters.append(f"{video_labels}concat=n={len(ranges)}:v=1:a=0[vout]")
        filters.append(f"{audio_labels}concat=n={len(ranges)}:v=0:a=1[aout]")
        command = [
            "ffmpeg", "-y", "-hide_banner", "-nostats", *inputs,
            "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
            "-movflags", "+faststart", str(output),
        ]
    else:
        # 无音轨素材（如 testsrc/静音导出）：只用视频分支，避免 [0:a] 匹配不到流直接失败。
        filters = []
        for index, (start, end) in enumerate(ranges):
            filters.append(f"[0:v]trim={start:.3f}:{end:.3f},setpts=PTS-STARTPTS[v{index}]")
        video_labels = "".join(f"[v{i}]" for i in range(len(ranges)))
        filters.append(f"{video_labels}concat=n={len(ranges)}:v=1:a=0[vout]")
        command = [
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", path,
            "-filter_complex", ";".join(filters), "-map", "[vout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-movflags", "+faststart", str(output),
        ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0 or not output.exists():
        raise RuntimeError(f"ffmpeg 裁剪失败：{(result.stderr or '')[-400:]}")
    return str(output)


def extract_video_frames(path: str, start: float, end: float, count: int, out_dir: str) -> list[str]:
    """按时间范围均匀抽 count 帧（一瞬入画的多帧参考来源）；返回 PNG 路径列表。"""
    count = max(1, min(int(count), 8))
    if end <= start:
        raise RuntimeError("抽帧结束时间必须大于开始时间。")
    info = probe_video(path)
    duration = info["seconds"] or 0
    end = min(end, duration) if duration else end
    if end <= start:
        raise RuntimeError(f"抽帧范围超出视频时长（源 {duration}s）。")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    step = (end - start) / count
    # 取每段中点时刻，避免首帧黑场
    stamps = [start + step * (index + 0.5) for index in range(count)]
    paths: list[str] = []
    stem = Path(path).stem[:24]
    for index, stamp in enumerate(stamps):
        target = out / f"ariadne-frame-{stem}-{uuid.uuid4().hex[:6]}-{index}.png"
        command = [
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
            "-ss", f"{stamp:.3f}", "-i", path, "-frames:v", "1", str(target),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except FileNotFoundError as error:
            raise RuntimeError("ffmpeg 不可用：请确认已安装并加入 PATH。") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"ffmpeg 抽帧超时（{stamp:.1f}s）。") from error
        if result.returncode != 0 or not target.exists():
            raise RuntimeError(f"ffmpeg 抽帧失败：{(result.stderr or '')[-300:]}")
        paths.append(str(target))
    return paths
