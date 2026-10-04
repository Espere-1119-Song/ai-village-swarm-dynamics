"""Voice-over for the demo video with the Kokoro TTS model; writes narration.wav next to this file.

Each line starts at a fixed time and must end before `until`, the end of its scene minus the fade; a line that
runs long is spoken faster, up to 1.2 times. Needs kokoro-onnx and soundfile, plus the model files
kokoro-v1.0.onnx and voices-v1.0.bin from https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
in the directory given as the first argument.
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

HERE = Path(__file__).resolve().parent
DURATION = 114.0333
VOICE = "af_heart"
LINES = [
    (1.0, 5.6, "How strongly do AI agents influence each other?"),
    (6.4, 15.6, "For eighteen months, the AI Village ran forty-six agents. We merge six kinds of logs into one event "
                "table of three point two million rows."),
    (16.5, 26.6, "We split the question into five: chat, memory, retelling, shared work, and scaffolding changes. "
                 "Each one gets its own method."),
    (27.5, 34.8, "In the chat, an excitation model asks what triggered each message. Almost half follow the agent's own "
                 "earlier messages."),
    (35.4, 41.6, "Cascades between agents die out in thirty-nine of forty-two goal windows."),
    (42.6, 55.6, "Agents rewrite their own memory. Fact tracking shows that a third of new facts vanish the first time "
                 "the memory is rewritten, while the facts that survive grow safer."),
    (56.6, 69.6, "Information retold between agents reaches fewer agents than it could. It slows down with every "
                 "retelling, and thirty percent of the numbers it carries change on the way."),
    (70.6, 77.8, "Dependency graphs show whose earlier work each session builds on. Most links stay within one agent."),
    (78.2, 85.6, "Real graphs skip far more layers than the model's. Six in ten sessions continue the agent's own work."),
    (86.6, 97.6, "Finally, behaviour changes do not line up with documented scaffold changes beyond chance. Instead, "
                 "they bunch on Mondays, when new goals start."),
    (98.5, 106.6, "Each step is one command that runs on ordinary CPUs, and every output holds only aggregate results."),
    (107.6, 113.8, "Code, write-up and results are all on GitHub."),
]


def main(model_dir: str) -> None:
    k = Kokoro(str(Path(model_dir) / "kokoro-v1.0.onnx"), str(Path(model_dir) / "voices-v1.0.bin"))
    sr = 24000
    track = np.zeros(int(round(DURATION * sr)), dtype=np.float32)
    for start, until, text in LINES:
        speed = 1.0
        s, sr_ = k.create(text, voice=VOICE, speed=speed, lang="en-us")
        if len(s) / sr_ > until - start:
            speed = min(1.2, 1.02 * (len(s) / sr_) / (until - start))
            s, sr_ = k.create(text, voice=VOICE, speed=speed, lang="en-us")
        assert sr_ == sr
        i = int(round(start * sr))
        s = s[: max(0, len(track) - i)]
        track[i:i + len(s)] += s
        print(f"{start:6.1f} s  {len(s) / sr:5.2f} s of {until - start:5.2f} s  speed {speed:.2f}  {text[:50]}")
    sf.write(HERE / "narration.wav", track, sr)


if __name__ == "__main__":
    main(sys.argv[1])
