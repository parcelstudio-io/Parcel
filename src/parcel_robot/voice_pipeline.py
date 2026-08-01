from __future__ import annotations

from collections.abc import Callable

from .agent import VoiceAgent
from .providers import SpeechRecognizer, SpeechSynthesizer


class VoicePipeline:
    """One utterance through STT, guarded intelligence, and TTS.

    Audio capture/playback remain callbacks so ROS or the target sound hardware
    can own device selection, echo cancellation, and interruption.
    """

    def __init__(
        self,
        recognizer: SpeechRecognizer,
        agent: VoiceAgent,
        synthesizer: SpeechSynthesizer,
        audio_player: Callable[[bytes], None],
    ):
        self.recognizer = recognizer
        self.agent = agent
        self.synthesizer = synthesizer
        self.audio_player = audio_player

    def process(self, wav_audio: bytes) -> tuple[str, str]:
        transcript = self.recognizer.transcribe(wav_audio)
        if not transcript:
            return "", ""
        reply = self.agent.handle_text(transcript)
        if reply:
            self.audio_player(self.synthesizer.synthesize(reply))
        return transcript, reply

