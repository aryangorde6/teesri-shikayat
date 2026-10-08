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


# --- the case (spec §7 texts 6–10). Numbers and names are filled by code. ---------------------------
ILLNESS_HI = {"diarrhoea": "दस्त", "vomiting": "उल्टी", "fever": "बुखार", "stomach_pain": "पेट दर्द",
              "jaundice": "पीलिया", "skin_rash": "त्वचा पर दाने"}
VULNERABLE_OBL = {"child": "बच्चे", "elderly": "बुज़ुर्ग", "pregnant": "गर्भवती महिला"}

VOLUNTEER_CARD = "{summary}\n📍 {homes} घर · {spread_m} मीटर · {hours} घंटे — क्या पूरे इलाके को चेतावनी भेजें?"
APPROVE_YES, APPROVE_NO = "हाँ, भेजें", "अभी नहीं"
APPROVED_ACK = "✅ ठीक है, इलाके के सभी जुड़े घरों को चेतावनी भेजी जा रही है।"
HELD_ACK = "ठीक है, अभी चेतावनी नहीं भेजी गई। केस खुला है।"
EXPIRED = "यह सवाल अब पुराना हो गया है।"

RING_WARNING = ("⚠️ चेतावनी: आपके पास के {homes} घरों से गंदे पानी की शिकायत आई है। पाइप में लीकेज हो सकता है।\n"
                "• पीने का पानी कम से कम 1 मिनट उबालकर पिएँ।\n• दस्त हो तो ORS लें।\n"
                "• बुखार, उल्टी या मल में खून हो तो तुरंत डॉक्टर को दिखाएँ। नज़दीकी अस्पताल: {clinic}।\n"
                "यह संदेश अपने पड़ोसियों को भी भेजें।")
WARD_CLAIM_VOLUNTEER = 'वार्ड ऑफिस का कहना है: "{claim}"। केस बंद करने से पहले इलाके के घरों से पूछा जा रहा है।'
CHECKIN = "वार्ड ऑफिस का कहना है कि समस्या ठीक हो गई है। क्या आपके नल का पानी अब साफ़ है?"
CHECKIN_YES, CHECKIN_NO = "हाँ, साफ़ है", "नहीं, अभी भी गंदा"
CHECKIN_THANKS = "धन्यवाद, आपका जवाब दर्ज हो गया।"
REOPENED = 'आपके इलाके से "अभी भी गंदा" जवाब आया है। केस दोबारा खोला गया है। पानी उबालकर ही पिएँ।'
CLOSED = "{n} घरों ने पुष्टि की कि पानी साफ़ है। केस बंद। धन्यवाद 🙏"
STILL_OPEN_VOLUNTEER = "पर्याप्त घरों ने जवाब नहीं दिया, इसलिए केस बंद नहीं हुआ। केस खुला है।"
