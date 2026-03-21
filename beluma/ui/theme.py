"""Gradio CSS teması — Neon Mor & Pembe."""

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700&family=Inter:wght@400;500&display=swap');
body {
    background: #0d0614 !important;
    font-family: 'Inter', sans-serif !important;
}
body::before {
    content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background:
        radial-gradient(circle at 15% 10%, rgba(138,43,226,.25), transparent 35%),
        radial-gradient(circle at 85% 5%,  rgba(255,20,147,.25),  transparent 30%),
        radial-gradient(circle at 50% 90%, rgba(138,43,226,.15), transparent 40%);
}
.gradio-container { max-width: 1000px !important; margin: 0 auto !important; position: relative; z-index: 1; }
.block { border: none !important; background: transparent !important; }
.beluma-hero { padding: 36px 0 6px; text-align: center; }
.beluma-hero h1 {
    margin: 0; font-family: 'Montserrat', sans-serif;
    font-size: 2.8rem; letter-spacing: .04em; font-weight: 700;
    background: linear-gradient(90deg, #FF1493 0%, #8A2BE2 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.beluma-hero p { max-width: 680px; margin: 10px auto 6px; color: rgba(255,255,255,.85); line-height: 1.7; font-size: .97rem; }
.beluma-soft { text-align: center; color: #FF69B4; font-size: .9rem; margin-bottom: 10px; opacity: .8; }
.beluma-status {
    text-align: center; font-size: .9rem; margin: 4px 0 12px;
    color: rgba(255,255,255,.65);
    display: flex; align-items: center; justify-content: center; gap: 7px;
}
.beluma-status::before {
    content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: #FF1493; box-shadow: 0 0 8px rgba(255,20,147,.9);
    animation: pulse-led 2s ease-in-out infinite;
}
@keyframes pulse-led {
    0%,100% { opacity: 1; transform: scale(1); }
    50%      { opacity: .4; transform: scale(.85); }
}
.tab-nav { border-bottom: 1px solid rgba(138,43,226,.2) !important; }
.tab-nav button {
    color: rgba(255,255,255,.55) !important; font-size: .95rem !important; font-weight: 500 !important;
    border-radius: 10px 10px 0 0 !important;
    transition: color .2s, background .2s !important; padding: 10px 16px !important;
}
.tab-nav button:hover { color: #FF1493 !important; background: rgba(255,20,147,.08) !important; }
.tab-nav button.selected {
    color: #fff !important;
    background: linear-gradient(180deg, rgba(138,43,226,.25), rgba(255,20,147,.1)) !important;
    border-bottom: 2px solid #FF1493 !important;
    text-shadow: 0 0 12px rgba(255,20,147,.6) !important;
}
.gradio-chatbot {
    border: 1px solid rgba(138,43,226,.3) !important; border-radius: 20px !important;
    background: rgba(13,6,20,.85) !important;
    box-shadow: 0 8px 40px rgba(0,0,0,.6), 0 0 0 1px rgba(255,20,147,.1) !important;
}
.gradio-chatbot .user > div, .gradio-chatbot [data-testid="user"] > div {
    background: linear-gradient(135deg, #FF1493, #C71585) !important;
    color: #fff !important; border-radius: 18px 18px 4px 18px !important;
    box-shadow: 0 4px 15px rgba(255,20,147,.3) !important;
}
.gradio-chatbot .bot > div, .gradio-chatbot [data-testid="bot"] > div {
    background: linear-gradient(135deg, #8A2BE2, #4B0082) !important;
    color: rgba(255,255,255,.95) !important; border-radius: 18px 18px 18px 4px !important;
    border: 1px solid rgba(138,43,226,.4) !important;
    box-shadow: 0 4px 15px rgba(138,43,226,.2) !important;
}
.gradio-textbox, .gradio-dropdown, .gradio-accordion,
.gradio-file, .gradio-image, .gradio-audio { border-radius: 14px !important; }
.gradio-textbox textarea, .gradio-textbox input {
    font-family: 'Inter', sans-serif !important; font-size: .97rem !important; line-height: 1.6 !important;
    background: rgba(255,255,255,.03) !important;
    border: 1px solid rgba(138,43,226,.3) !important;
    color: rgba(255,255,255,.95) !important; border-radius: 14px !important;
    transition: border-color .3s, box-shadow .3s !important;
}
.gradio-textbox textarea:focus, .gradio-textbox input:focus {
    border-color: #FF1493 !important;
    box-shadow: 0 0 0 3px rgba(255,20,147,.25) !important; outline: none !important;
}
button.primary {
    background: linear-gradient(135deg, #FF1493, #8A2BE2) !important;
    color: #fff !important; border: none !important; border-radius: 14px !important;
    font-weight: 600 !important; box-shadow: 0 4px 15px rgba(255,20,147,.4) !important;
    transition: transform .15s, box-shadow .15s, filter .15s !important;
}
button.primary:hover {
    transform: scale(1.04) !important; box-shadow: 0 6px 22px rgba(138,43,226,.6) !important;
    filter: brightness(1.15) !important;
}
button.primary:active { transform: scale(.97) !important; }
button.secondary {
    background: rgba(138,43,226,.1) !important; color: rgba(255,255,255,.85) !important;
    border: 1px solid rgba(138,43,226,.4) !important; border-radius: 14px !important;
    font-weight: 500 !important;
    transition: background .2s, border-color .2s, transform .15s !important;
}
button.secondary:hover {
    background: rgba(255,20,147,.2) !important; border-color: #FF1493 !important;
    color: #fff !important; transform: scale(1.03) !important;
}
button.secondary:active { transform: scale(.97) !important; }
button.stop {
    background: rgba(200,40,40,.2) !important; border: 1px solid rgba(200,40,40,.4) !important;
    color: #ff6b6b !important; border-radius: 14px !important;
}
button.stop:hover { background: rgba(200,40,40,.35) !important; }
.belge-upload-btn {
    height: 100% !important; min-height: 42px !important;
    border-radius: 14px !important; font-size: .97rem !important; font-weight: 500 !important;
    background: rgba(138,43,226,.15) !important; border: 1px solid rgba(138,43,226,.4) !important;
    color: rgba(255,255,255,.9) !important; cursor: pointer !important;
    transition: background .2s, border-color .2s, transform .15s !important;
    display: flex !important; align-items: center !important;
    justify-content: center !important; align-self: center !important;
}
.belge-upload-btn:hover {
    background: rgba(255,20,147,.25) !important; border-color: #FF1493 !important;
    color: #fff !important; transform: scale(1.03) !important;
}
.belge-upload-btn > .wrap {
    display: flex !important; align-items: center !important;
    justify-content: center !important; height: 100% !important;
}
.examples { margin-top: 10px !important; }
.examples .label { color: rgba(255,255,255,.4) !important; font-size: .82rem !important; }
.examples table td, .examples .example {
    background: rgba(138,43,226,.1) !important;
    border: 1px solid rgba(138,43,226,.3) !important; border-radius: 10px !important;
    color: rgba(255,255,255,.8) !important; font-size: .88rem !important;
    transition: background .2s, color .2s, transform .15s, box-shadow .2s !important;
    cursor: pointer !important;
}
.examples table td:hover, .examples .example:hover {
    background: linear-gradient(135deg, rgba(255,20,147,.2), rgba(138,43,226,.2)) !important;
    border-color: #FF1493 !important; color: #fff !important;
    transform: scale(1.03) !important; box-shadow: 0 4px 12px rgba(255,20,147,.2) !important;
}
.think-box {
    background: rgba(138,43,226,.1); border-left: 3px solid #FF1493;
    border-radius: 0 10px 10px 0; padding: 10px 16px;
    font-size: .88rem; color: rgba(255,255,255,.7); margin-top: 8px;
}
.gradio-accordion {
    background: rgba(255,255,255,.02) !important;
    border: 1px solid rgba(138,43,226,.25) !important; border-radius: 14px !important;
}
@media (max-width: 640px) {
    .beluma-hero h1 { font-size: 2rem !important; }
    .gradio-container { padding: 0 8px !important; }
    button.primary, button.secondary { font-size: .85rem !important; padding: 8px 10px !important; }
}
"""
