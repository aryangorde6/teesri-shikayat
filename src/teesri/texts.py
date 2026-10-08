"""Every resident-facing message. `{}` slots are filled by code, never by a model."""

WELCOME = ('नमस्ते! "तीसरी शिकायत" में आपका स्वागत है। 🚰 हम आपके इलाके की गंदे पानी की शिकायतें '
           'जोड़कर पड़ोसियों को समय पर चेतावनी देते हैं। कृपया नीचे "📍 लोकेशन भेजें" बटन दबाएँ।')
SEND_LOCATION = "📍 लोकेशन भेजें"
CONSENT = 'आपका नाम और नंबर किसी से शेयर नहीं होगा। जुड़ने के लिए "हाँ" दबाएँ।'
JOINED = "आप जुड़ गए ✅ जब भी नल का पानी गंदा लगे, बस एक वॉइस नोट भेजें।"
DECLINED = "ठीक है। आपकी कोई जानकारी नहीं रखी गई। जुड़ना हो तो /start भेजें।"
LOCATION_UPDATED = "लोकेशन अपडेट हो गई ✅"
SEND_VOICE = "नल का पानी गंदा लगे तो बस एक वॉइस नोट भेजें 🎙️"

FALLBACK_COLOUR = "माफ़ कीजिए, आवाज़ साफ़ नहीं आई। पानी का रंग कैसा है?"  # nothing heard
ASK_COLOUR = "शुक्रिया! पानी का रंग कैसा है?"                           # heard, but no colour/smell said
ASK_SMELL = "बदबू है?"
ASK_SINCE = "कब से?"

YES, NO = "हाँ", "नहीं"
COLOUR_HI = {"yellow": "पीला", "brown": "भूरा", "black": "काला", "clear": "साफ़"}
COLOUR_BUTTONS = [("पीला", "yellow"), ("भूरा", "brown"), ("काला", "black")]
SINCE_BUTTONS = [("आज", 0), ("2-3 दिन", 3), ("हफ़्ते से ज़्यादा", 8)]

# One building (all reports within 30 m): likely the building's tank, not the street pipe. No area alarm.
TANK_ADVICE = ("आपकी बिल्डिंग के {n} घरों से गंदे पानी की शिकायत आई है, आस-पास की बिल्डिंगों से नहीं। "
               "हो सकता है आपकी पानी की टंकी गंदी हो। • टंकी साफ़ करवाएँ। • तब तक पीने का पानी उबालकर पिएँ।")


def receipt(f: dict) -> str:
    """आपकी शिकायत मिल गई: {colour_hi} पानी, {since_days} दिन से। ..."""
    if f.get("colour") in COLOUR_HI:
        what = f"{COLOUR_HI[f['colour']]}{', बदबूदार' if f.get('smell') else ''} पानी"
    else:
        what = "बदबूदार पानी" if f.get("smell") else "गंदा पानी"
    since = f.get("since_days")
    when = "" if since is None else (", आज से" if since == 0 else f", {since} दिन से")
    return f"आपकी शिकायत मिल गई: {what}{when}। हम आस-पास की शिकायतें देख रहे हैं।"
