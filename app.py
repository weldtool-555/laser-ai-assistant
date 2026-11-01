import streamlit as st
import ezdxf
from ezdxf import colors
import json, io, re, urllib.request, urllib.error
import matplotlib.pyplot as plt

st.set_page_config(page_title="Laser Cut DXF Assistant", layout="wide")
st.title("⚡ レーザー加工専用 AIアシスタント")
st.caption("CypCut完全準拠（外枠=White / 内穴=Pink）DXF自動生成システム")

api_key = st.sidebar.text_input("Gemini API Key を入力", type="password")

def build_cypcut_dxf(data):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    
    doc.layers.get("0").color = colors.WHITE
    if "1" not in doc.layers:
        doc.layers.add(name="1", color=6)

    outer = data.get("outer", {})
    w = float(outer.get("width", 150))
    h = float(outer.get("height", 100))
    r = float(outer.get("corner_radius", 0))
    
    if r <= 0:
        msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h), (0, 0)], dxfattribs={"layer": "0"})
    else:
        msp.add_line((r, 0), (w - r, 0), dxfattribs={"layer": "0"})
        msp.add_arc((w - r, r), r, 270, 360, dxfattribs={"layer": "0"})
        msp.add_line((w, r), (w, h - r), dxfattribs={"layer": "0"})
        msp.add_arc((w - r, h - r), r, 0, 90, dxfattribs={"layer": "0"})
        msp.add_line((w - r, h), (r, h), dxfattribs={"layer": "0"})
        msp.add_arc((r, h - r), r, 90, 180, dxfattribs={"layer": "0"})
        msp.add_line((0, h - r), (0, r), dxfattribs={"layer": "0"})
        msp.add_arc((r, r), r, 180, 270, dxfattribs={"layer": "0"})
        
    for hole in data.get("holes", []):
        msp.add_circle((float(hole.get("x", 0)), float(hole.get("y", 0))), radius=float(hole.get("diameter", 6))/2.0, dxfattribs={"layer": "1"})
        
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8"), w, h, data.get("holes", []), r

def render_preview(w, h, holes, r):
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.add_patch(plt.Rectangle((0, 0), w, h, fill=False, edgecolor="green", linewidth=2))
    for hole in holes:
        ax.add_patch(plt.Circle((hole["x"], hole["y"]), hole["diameter"]/2.0, fill=False, edgecolor="magenta", linewidth=1.5))
    ax.set_xlim(-15, w + 15); ax.set_ylim(-15, h + 15); ax.set_aspect("equal"); ax.grid(True, linestyle="--", alpha=0.5)
    return fig

def fallback_parser(text):
    w, h, r = 150.0, 100.0, 5.0
    m_wh = re.search(r'(\d+)\s*[xX*×]\s*(\d+)', text)
    if m_wh:
        w, h = float(m_wh.group(1)), float(m_wh.group(2))
    m_r = re.search(r'[rR](\d+)', text)
    if m_r:
        r = float(m_r.group(1))
    
    # 端からのオフセット（「〜の位置に」の手前にある数値を優先抽出）
    m_offset = re.search(r'(\d+)\s*mm\s*の\s*位置', text)
    if m_offset:
        offset = float(m_offset.group(1))
    else:
        # 見つからない場合は20をデフォルトに
        offsets = re.findall(r'(\d+)\s*mm', text)
        offset = float(offsets[-1]) if offsets else 20.0

    m_dia = re.search(r'[φΦ](\d+)', text)
    dia = float(m_dia.group(1)) if m_dia else 6.0

    return {
        "outer": {"width": w, "height": h, "corner_radius": r},
        "holes": [
            {"x": offset, "y": offset, "diameter": dia},
            {"x": w - offset, "y": offset, "diameter": dia},
            {"x": offset, "y": h - offset, "diameter": dia},
            {"x": w - offset, "y": h - offset, "diameter": dia}
        ]
    }

def call_gemini(prompt_text, key):
    models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]
    payload = json.dumps({"contents": [{"parts": [{"text": prompt_text}]}]}).encode("utf-8")
    last_err = None
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        try:
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as res:
                res_json = json.loads(res.read().decode("utf-8"))
                return res_json["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            last_err = e
            continue
    raise last_err

PROMPT = "板金CAD用変換。指示文からouter(width, height, corner_radius)とholes(x, y, diameter)を計算し、純粋なJSONのみを返してください。"
user_prompt = st.text_area("形状の指示", value="150x100mmの角丸R5プレート。四隅の端からそれぞれ20mmの位置にφ6の穴を4つあけて。", height=100)

if st.button("DXFを生成する（テキスト）", type="primary"):
    with st.spinner("寸法データを計算・生成中..."):
        data = None
        if api_key.strip():
            try:
                reply_text = call_gemini(f"{PROMPT}\n指示: {user_prompt}", api_key.strip())
                m = re.search(r'\{.*\}', reply_text, re.DOTALL)
                json_text = m.group(0) if m else reply_text
                data = json.loads(json_text)
                st.session_state["mode"] = "Gemini AI生成"
            except Exception as e:
                data = fallback_parser(user_prompt)
                st.session_state["mode"] = f"自動寸法解析モード（API予備動作: {e}）"
        else:
            data = fallback_parser(user_prompt)
            st.session_state["mode"] = "ローカル直接計算モード"

        st.session_state["geo_data"] = data
        st.rerun()

if "geo_data" in st.session_state:
    st.divider()
    st.subheader("📐 解析結果 & CypCut用DXFプレビュー")
    if "mode" in st.session_state:
        st.caption(f"ステータス: {st.session_state['mode']}")
    c1, c2 = st.columns([1, 1])
    d = st.session_state["geo_data"]
    with c1:
        st.write("**抽出・計算された寸法データ（JSON）**")
        st.json(d)
    with c2:
        dxf_b, w, h, holes, r = build_cypcut_dxf(d)
        st.pyplot(render_preview(w, h, holes, r))
        st.download_button(
            label="📥 CypCut専用 DXFファイルをダウンロード",
            data=dxf_b,
            file_name="laser_part_cypcut.dxf",
            mime="application/dxf",
            type="primary"
        )
        st.success("✅ CypCut仕様（外枠=White / 内穴=Pink）で生成完了！そのままCypCutにドラッグ＆ドロップ可能です。")