import streamlit as st
import ezdxf
from ezdxf import colors
import json, io, re, os, time
import matplotlib.pyplot as plt
from google import genai

st.set_page_config(page_title="Laser Cut DXF & CypCut Assistant", layout="wide")
st.title("⚡ レーザー加工 & CypCut専用 AIアシスタント")
st.caption("社内マニュアル・CypCut完全準拠（外枠=White / 内穴=Pink）DXF自動生成 & 相談QA")

api_key = st.sidebar.text_input("Gemini API Key を入力", type="password")

# --- 複数ナレッジファイルの読み込み ---
def load_knowledge():
    files_to_load = [
        ("CypCut操作説明書", "cypcut_manual.txt"),
        ("レーザー切断条件・パラメータ表", "cutting_conditions.txt"),
        ("社内作図・加工ルール", "knowledge.txt")
    ]
    combined_knowledge = []
    
    for label, filename in files_to_load:
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        combined_knowledge.append(f"=== 【{label} ({filename})】 ===\n{content}")
            except Exception as e:
                combined_knowledge.append(f"=== 【{label} ({filename})】 ===\n読み込みエラー: {e}")
                
    if combined_knowledge:
        return "\n\n".join(combined_knowledge)
    return "（社内ナレッジファイルはまだ設定されていません）"

knowledge_data = load_knowledge()

with st.sidebar.expander("📚 参照中の社内マニュアル・切断条件"):
    st.text(knowledge_data)

# --- CypCut用 DXF生成ロジック ---
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
    
    m_offset = re.search(r'(\d+)\s*mm\s*の\s*位置', text)
    offset = float(m_offset.group(1)) if m_offset else 20.0
    m_dia = re.search(r'[φΦ](\d+)', text)
    dia = float(m_dia.group(1)) if m_dia else 6.0

    return {
        "outer": {
            "width": w,
            "height": h,
            "corner_radius": r
        },
        "holes": [
            {"x": offset, "y": offset, "diameter": dia},
            {"x": w - offset, "y": offset, "diameter": dia},
            {"x": offset, "y": h - offset, "diameter": dia},
            {"x": w - offset, "y": h - offset, "diameter": dia}
        ]
    }

# --- gemini-3.8-flash 呼出（混雑時は自動待機リトライ） ---
def call_gemini(prompt_text, key):
    client = genai.Client(api_key=key.strip())
    last_err = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt_text,
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise last_err

# --- タブレイアウト ---
tab_dxf, tab_chat = st.tabs(["📐 CypCut用DXF作図", "💬 CypCut操作・加工相談QA"])

# タブ1: DXF作図画面
with tab_dxf:
    st.subheader("図面指示からCypCut用DXFを自動生成")
    user_prompt = st.text_area("形状の指示文", value="150x100mmの角丸R5プレート。四隅の端からそれぞれ20mmの位置にφ6の穴を4つあけて。", height=100)

    if st.button("DXFを生成する（テキスト）", type="primary"):
        with st.spinner("社内ルール照合 & 寸法生成中..."):
            data = None
            if api_key.strip():
                try:
                    dxf_prompt = f"""
あなたは板金レーザー加工の専門CADアシスタントです。
以下の【社内ナレッジ（操作説明書・切断条件・ルール）】を最優先で遵守して、指示文から outer(width, height, corner_radius) と holes(x, y, diameter) のJSONデータのみを出力してください。

【社内ナレッジ】
{knowledge_data}

指示文: {user_prompt}
"""
                    reply_text = call_gemini(dxf_prompt, api_key)
                    m = re.search(r'\{.*\}', reply_text, re.DOTALL)
                    json_text = m.group(0) if m else reply_text
                    data = json.loads(json_text)
                    st.session_state["mode"] = "Gemini AI（社内ルール適用）"
                except Exception as e:
                    data = fallback_parser(user_prompt)
                    st.session_state["mode"] = f"自動寸法解析モード（予備動作: {e}）
