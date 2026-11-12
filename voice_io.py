import speech_recognition as sr
import pyttsx3

_recognizer = sr.Recognizer()
_tts_engine = pyttsx3.init()


def listen() -> str:
    """Press Enter, then speak. Recording stops automatically once you pause --
    the library's own silence detection, not a second keypress."""
    input("Press Enter, then start speaking...")
    with sr.Microphone() as source:
        _recognizer.adjust_for_ambient_noise(source, duration=0.5)
        print("Listening...")
        audio = _recognizer.listen(source)

    try:
        text = _recognizer.recognize_google(audio)
        print(f"[heard]: {text}")
        return text
    except sr.UnknownValueError:
        print("[could not understand audio]")
        return ""
    except sr.RequestError as e:
        print(f"[speech recognition service error: {e}]")
        return ""


def speak(text: str) -> None:
    _tts_engine.say(text)
    _tts_engine.runAndWait()


if __name__ == "__main__":
    heard = listen()
    if heard:
        print(f"You said: {heard}")
        speak(f"You said: {heard}")
    else:
        print("Nothing recognized.")