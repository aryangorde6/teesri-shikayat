"""Channel adapter: core code talks to households by id, never to a messaging API directly.

`tg<chat_id>` -> Telegram. `sim-<x>` -> the simulated phone wall (messages stored in DynamoDB).
A WhatsApp adapter would add one more prefix here; nothing upstream changes.
"""
from teesri import store, telegram

Buttons = list[list[tuple[str, str]]]  # rows of (label, callback data)


def send_text(hh_id: str, text: str, buttons: Buttons | None = None, location_keyboard: str | None = None) -> None:
    if hh_id.startswith("tg"):
        markup = None
        if buttons:
            markup = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
        elif location_keyboard:
            markup = {"keyboard": [[{"text": location_keyboard, "request_location": True}]],
                      "resize_keyboard": True, "one_time_keyboard": True}
        telegram.send_message(int(hh_id[2:]), text, **({"reply_markup": markup} if markup else {}))
    elif hh_id.startswith("sim-"):
        _to_wall(hh_id, {"kind": "text", "text": text, "buttons": buttons or []})
    else:
        raise ValueError(f"unknown channel for {hh_id}")


def send_voice(hh_id: str, mp3: bytes, audio_key: str = "") -> None:
    if hh_id.startswith("tg"):
        telegram.send_voice(int(hh_id[2:]), mp3)
    elif hh_id.startswith("sim-"):
        _to_wall(hh_id, {"kind": "voice", "audio_key": audio_key})
    else:
        raise ValueError(f"unknown channel for {hh_id}")


def _to_wall(hh_id: str, msg: dict) -> None:
    store.table().put_item(Item=store._dec({"PK": f"HH#{hh_id}", "SK": f"MSG#{store.now_iso()}#{store.new_id()}", **msg}))
