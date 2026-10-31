#!/usr/bin/env python3
"""Synthetic-only, blinded audio research; never an approval or production input."""
import base64
import json
import os
import random
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"


def run(args):
    subprocess.run(args, check=True, capture_output=True, timeout=60)


def main():
    key = os.environ["NVIDIA_API_KEY"]
    labels = ["clean", "noise", "dropout", "pumping"]
    random.SystemRandom().shuffle(labels)
    filters = {"clean": "anull", "noise": "anoisesrc=color=white:amplitude=0.10[noise];[0:a][noise]amix=inputs=2:duration=first",
               "dropout": "volume='if(between(t,2,3.2),0,1)':eval=frame",
               "pumping": "volume='if(lt(mod(t,0.7),0.35),0.12,1)':eval=frame"}
    result = {"schema": "nemotron-synthetic-audio-research-v2", "model": MODEL, "results": [],
              "labels": {}, "release_approved": False}
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        source = base / "source.wav"
        run(["espeak-ng", "-s", "155", "-w", str(source), "The manager checked the report before the meeting. Every figure had a source, and the team corrected the mistake before sending the result to their customers."])
        for i, label in enumerate(labels):
            blind = chr(65 + i)
            result["labels"][blind] = label
            wav = base / (blind + ".wav")
            args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
            args += ["-filter_complex" if label == "noise" else "-af", filters[label], "-ar", "16000", "-ac", "1", str(wav)]
            run(args)
            encoded = base64.b64encode(wav.read_bytes()).decode("ascii")
            body = {"model": MODEL, "messages": [{"role": "user", "content": [
                {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64," + encoded}},
                {"type": "text", "text": "Listen to the entire recording. Describe unintended interruptions, unwanted noise, or rhythmic changes in loudness. Is it clean or defective?"}]}],
                "max_tokens": 1024, "temperature": 0.0, "stream": False,
                "chat_template_kwargs": {"enable_thinking": False}}
            request = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = json.load(response)
                    message = data.get("choices", [{}])[0].get("message", {})
                    result["results"].append({"blind_id": blind, "http": response.status,
                                             "content": str(message.get("content") or "")[:8000],
                                             "finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
                                             "usage": data.get("usage")})
            except urllib.error.HTTPError as exc:
                result["results"].append({"blind_id": blind, "http": exc.code})
                break  # Respect quota, auth and provider errors; no retries.
            except Exception as exc:
                result["results"].append({"blind_id": blind, "error": type(exc).__name__})
                break
    Path(os.environ["RUNNER_TEMP"], "nemotron-audio-results.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
