// Voz: STT (Web Speech API) + TTS (speechSynthesis).

class Voice {
    constructor() {
        this.recognition = null;
        this.synthVoice = null;
        this.listening = false;
        this.onTranscript = null;
        this.onListenStart = null;
        this.onListenEnd = null;
        this.onSpeakStart = null;
        this.onSpeakEnd = null;
        this.onAudioFrame = null; // callback(level) durante TTS

        this._setupRecognition();
        this._setupSynthesis();
    }

    _setupRecognition() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            console.warn('SpeechRecognition indisponível — apenas entrada por texto.');
            return;
        }
        const rec = new SR();
        rec.lang = 'pt-BR';
        rec.continuous = false;
        rec.interimResults = false;
        rec.maxAlternatives = 1;

        rec.onstart = () => {
            this.listening = true;
            if (this.onListenStart) this.onListenStart();
        };
        rec.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            if (this.onTranscript) this.onTranscript(transcript);
        };
        rec.onerror = (e) => {
            console.warn('reconhecimento de voz:', e.error);
        };
        rec.onend = () => {
            this.listening = false;
            if (this.onListenEnd) this.onListenEnd();
        };
        this.recognition = rec;
    }

    _setupSynthesis() {
        const pickVoice = () => {
            const voices = speechSynthesis.getVoices();
            // Prefer Portuguese (Brazil) voices
            const ptBR = voices.find(v => v.lang === 'pt-BR' && /maria|francisca|daniel/i.test(v.name))
                      || voices.find(v => v.lang === 'pt-BR')
                      || voices.find(v => v.lang.startsWith('pt'));
            this.synthVoice = ptBR || voices[0] || null;
        };
        pickVoice();
        if (speechSynthesis.onvoiceschanged !== undefined) {
            speechSynthesis.onvoiceschanged = pickVoice;
        }
    }

    startListening() {
        if (!this.recognition || this.listening) return false;
        try { this.recognition.start(); } catch (e) { console.warn(e); return false; }
        return true;
    }

    stopListening() {
        if (this.recognition && this.listening) this.recognition.stop();
    }

    speak(text) {
        if (!text || !window.speechSynthesis) return;
        speechSynthesis.cancel();
        const utt = new SpeechSynthesisUtterance(text);
        if (this.synthVoice) utt.voice = this.synthVoice;
        utt.lang = 'pt-BR';
        utt.rate = 1.0;
        utt.pitch = 0.95;
        utt.volume = 1.0;
        utt.onstart = () => {
            if (this.onSpeakStart) this.onSpeakStart();
            // Fake audio reactivity: pulse during speech
            this._fakeAudioLoop = setInterval(() => {
                if (this.onAudioFrame) {
                    this.onAudioFrame(0.4 + Math.random() * 0.6);
                }
            }, 60);
        };
        const stop = () => {
            clearInterval(this._fakeAudioLoop);
            if (this.onAudioFrame) this.onAudioFrame(0);
            if (this.onSpeakEnd) this.onSpeakEnd();
        };
        utt.onend = stop;
        utt.onerror = stop;
        speechSynthesis.speak(utt);
    }

    cancel() {
        if (window.speechSynthesis) speechSynthesis.cancel();
    }
}

window.voice = new Voice();
