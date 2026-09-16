"""Capa visual: mismo lenguaje de diseno que el Catalogo Control Center."""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path

import streamlit as st

from .icons import icon

BRAND_PRIMARY = "#17269A"
BRAND_BLUE = "#2367FF"
BRAND_ACCENT = "#009FE3"
NAVY = "#152238"

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def image_data_uri(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "webp": "webp", "svg": "svg+xml"}
    suffix = mime.get(path.suffix.lower().lstrip("."), "png")
    return f"data:image/{suffix};base64,{base64.b64encode(path.read_bytes()).decode()}"


def html(markup: str, sidebar: bool = False) -> None:
    target = st.sidebar if sidebar else st
    target.markdown(markup, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def login_styles() -> None:
    st.markdown(
        f"""
        <style>
        /* En el login no hay contenido de sidebar, asi que Streamlit no lo monta.
           No se usa display:none porque eso lo deja marcado como colapsado y
           despues no vuelve a aparecer. */
        [data-testid="stToolbar"], .stDeployButton, header[data-testid="stHeader"] {{ display:none !important; }}
        [data-testid="stAppViewContainer"] {{
            background:
                radial-gradient(1200px 620px at 12% -10%, #24407A 0%, transparent 60%),
                radial-gradient(900px 520px at 92% 8%, #10306E 0%, transparent 58%),
                {NAVY};
        }}
        .main .block-container {{ padding-top:44px; max-width:620px; }}
        .st-key-login_card {{
            width:min(452px, calc(100vw - 32px));
            margin:0 auto; overflow:hidden; border-radius:18px; background:#FFFFFF;
            box-shadow:0 34px 90px rgba(3,10,32,.46); color-scheme:light;
        }}
        .login-head {{
            padding:34px 32px 32px; text-align:center;
            background:linear-gradient(180deg, {BRAND_BLUE} 0%, #1757EF 100%);
            color:#FFFFFF;
        }}
        .login-logo-row {{
            display:flex; align-items:center; justify-content:center; gap:20px; margin-bottom:22px;
        }}
        .login-forus-logo {{
            min-width:178px; height:64px; border-radius:12px; background:#FFFFFF;
            display:grid; place-items:center; padding:8px 14px; box-sizing:border-box;
        }}
        .login-forus-logo img {{ max-width:100%; max-height:48px; object-fit:contain; }}
        .login-forus-fallback {{
            color:#14306B; font-size:34px; line-height:1; font-weight:950; letter-spacing:.02em;
        }}
        .login-forus-fallback small {{
            display:block; margin-top:3px; color:#14306B; font-size:8px;
            letter-spacing:.22em; font-weight:900;
        }}
        .login-divider {{ width:1px; height:48px; background:rgba(255,255,255,.62); }}
        .login-app-badge {{
            width:56px; height:56px; border-radius:14px; background:#FFFFFF;
            display:grid; place-items:center; box-shadow:0 10px 22px rgba(15,23,42,.14);
            font-size:26px;
        }}
        .login-head h1 {{ margin:0; font-size:28px; line-height:1.14; font-weight:950; }}
        .login-head p {{ margin:10px 0 0; color:#EAF2FF; font-size:15px; font-weight:750; }}
        .st-key-login_form_area {{ padding:24px 32px 26px; background:#FFFFFF; color-scheme:light; }}
        .st-key-login_form_area label {{ color:#1E293B !important; font-weight:850 !important; }}
        .st-key-login_form_area .stTextInput input {{
            border-radius:12px; min-height:48px; background:#F8FAFC !important;
            border:1px solid #CBD5E1 !important; font-size:15px; color:#0F172A !important;
            caret-color:#0F172A !important; -webkit-text-fill-color:#0F172A !important;
            opacity:1 !important; color-scheme:light !important;
        }}
        .st-key-login_form_area .stTextInput input::placeholder {{
            color:#64748B !important; -webkit-text-fill-color:#64748B !important; opacity:1 !important;
        }}
        .st-key-login_form_area div[data-baseweb="input"],
        .st-key-login_form_area div[data-baseweb="base-input"] {{
            background:#F8FAFC !important; color:#0F172A !important; color-scheme:light !important;
        }}
        .st-key-login_form_area .stTextInput input:-webkit-autofill {{
            -webkit-text-fill-color:#0F172A !important;
            -webkit-box-shadow:0 0 0 1000px #F8FAFC inset !important;
            transition:background-color 9999s ease-out 0s;
        }}
        .st-key-login_form_area .stButton button,
        .st-key-login_form_area button[data-testid^="stBaseButton"] {{
            width:100%; min-height:48px; border-radius:12px; background:{BRAND_BLUE};
            border-color:{BRAND_BLUE}; font-weight:950; white-space:nowrap !important;
        }}
        .login-brands {{
            display:flex; flex-wrap:wrap; align-items:center; justify-content:center;
            gap:14px 20px; padding:16px 28px 4px; background:#FFFFFF;
            border-top:1px solid #EEF2F8;
        }}
        .brand-chip {{
            display:grid; place-items:center; height:22px;
        }}
        .brand-chip img {{
            max-height:22px; max-width:76px; object-fit:contain;
            filter:grayscale(1); opacity:.42; transition:filter .2s, opacity .2s;
        }}
        .login-brands:hover .brand-chip img {{ filter:grayscale(0); opacity:.9; }}
        .login-note {{
            padding:12px 32px 30px; text-align:center; color:#64748B; font-size:13px; font-weight:750;
            background:#FFFFFF;
        }}
        .login-foot {{
            margin:26px auto 0; width:min(452px, calc(100vw - 32px)); text-align:center;
            color:#FFFFFF; font-size:14px; line-height:1.7; font-weight:750;
        }}
        .login-foot strong {{ display:block; margin-bottom:6px; font-weight:850; }}
        @media (max-width:560px) {{
            .main .block-container {{ padding-top:20px; }}
            .login-head {{ padding:26px 20px 26px; }}
            .st-key-login_form_area {{ padding:22px 22px 24px; }}
            .login-head h1 {{ font-size:24px; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------

def app_styles() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --brand-primary:{BRAND_PRIMARY};
            --brand-blue:{BRAND_BLUE};
            --brand-accent:{BRAND_ACCENT};
            --bg-main:#F6F8FC;
            --card-bg:#FFFFFF;
            --line:#E3EAF6;
            --text-main:#0F172A;
            --text-muted:#64748B;
        }}
        .stApp {{ background:var(--bg-main); color:var(--text-main); }}
        header[data-testid="stHeader"], div[data-testid="stToolbar"],
        div[data-testid="stDecoration"], #MainMenu, footer {{ display:none !important; height:0; }}
        .block-container {{ max-width:1280px; padding-top:22px; padding-bottom:56px; }}

        section[data-testid="stSidebar"] {{
            background:#F3F6FB; border-right:1px solid #DDE6F2;
            min-width:288px; width:288px;
        }}
        section[data-testid="stSidebar"] > div {{ padding:22px 16px; }}
        section[data-testid="stSidebar"] hr {{ margin:14px 0; border-color:#DFE7F3; }}
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span {{ color:#172554; }}

        /* ---------- cabecera del sidebar ---------- */
        .sb-brand {{
            display:flex; align-items:center; gap:12px; padding:12px 14px; margin-bottom:14px;
            background:#FFFFFF; border:1px solid var(--line); border-radius:14px;
            box-shadow:0 6px 16px rgba(15,23,42,.05);
        }}
        .sb-logo {{
            flex:0 0 auto; width:64px; height:34px; display:grid; place-items:center;
        }}
        .sb-logo img {{ max-width:64px; max-height:34px; object-fit:contain; }}
        .sb-fallback {{ font-size:15px; font-weight:950; color:{BRAND_PRIMARY}; }}
        .sb-txt {{ min-width:0; line-height:1.25; }}
        .sb-txt b {{ display:block; font-size:13.5px; font-weight:900; color:#0B1B46; }}
        .sb-txt span {{ display:block; font-size:11.5px; color:var(--text-muted); font-weight:650;
                        white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

        /* ---------- navegacion lateral ---------- */
        section[data-testid="stSidebar"] .sb-sec {{
            font-size:10.5px; font-weight:900; letter-spacing:.13em; text-transform:uppercase;
            color:#93A3BC; margin:18px 6px 8px;
        }}
        /* El boton ES la tarjeta: no hay nada superpuesto, por lo que toda la
           superficie es clickeable. El icono va en ::before y la descripcion
           en ::after. */
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] {{
            margin-bottom:6px;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button {{
            position:relative; display:block; width:100%; text-align:left;
            min-height:62px; padding:12px 14px 12px 58px;
            border-radius:13px; border:1px solid transparent; background:transparent;
            box-shadow:none; cursor:pointer;
            transition:background .15s, border-color .15s, box-shadow .15s;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button:hover {{
            background:#FFFFFF !important; border-color:var(--line) !important;
            box-shadow:0 4px 12px rgba(15,23,42,.06) !important;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button:focus:not(:active) {{
            border-color:#C9DAFF !important; color:inherit !important;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button::before {{
            content:""; position:absolute; left:12px; top:13px;
            width:34px; height:34px; border-radius:10px;
            background-repeat:no-repeat; background-position:center;
            background-size:19px 19px;
            transition:background-color .15s;
        }}
        /* Streamlit centra el contenido del boton con flex; aqui se alinea a la
           izquierda para que el nombre arranque pegado al icono. */
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button > div,
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button > div > span {{
            justify-content:flex-start !important;
            align-items:flex-start !important;
            width:100% !important;
            text-align:left !important;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button p {{
            margin:0; font-size:13px; line-height:1.25; text-align:left !important;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button::after {{
            display:block; margin-top:2px;
            font-size:11px; font-weight:650; line-height:1.3;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
        }}

        .sb-foot {{
            display:flex; align-items:center; gap:7px; margin-top:18px; padding:9px 12px;
            border-radius:11px; background:#EDF1F8; color:#5B6B86;
            font-size:11.5px; font-weight:750;
        }}
        .sb-foot svg {{ flex:0 0 auto; }}

        /* ---------- hero ---------- */
        .hero {{
            position:relative; overflow:hidden; border-radius:22px; padding:26px 30px;
            background:linear-gradient(125deg, #101B70 0%, {BRAND_PRIMARY} 42%, {BRAND_BLUE} 100%);
            color:#FFFFFF; box-shadow:0 24px 48px rgba(16,27,112,.24); margin-bottom:22px;
        }}
        .hero::after {{
            content:""; position:absolute; right:-90px; top:-120px; width:340px; height:340px;
            border-radius:50%; background:rgba(255,255,255,.09);
        }}
        .hero h1 {{ margin:0; font-size:27px; font-weight:950; letter-spacing:-.01em; }}
        .hero p {{ margin:8px 0 0; color:#D8E4FF; font-size:14.5px; font-weight:650; max-width:760px; }}
        .hero .eyebrow {{
            display:inline-block; margin-bottom:10px; padding:5px 12px; border-radius:999px;
            background:rgba(255,255,255,.16); font-size:11px; font-weight:900;
            letter-spacing:.14em; text-transform:uppercase;
        }}

        /* ---------- stepper ---------- */
        .stepper {{ display:flex; gap:8px; margin:0 0 22px; flex-wrap:wrap; }}
        .step {{
            flex:1 1 150px; min-width:140px; padding:12px 14px; border-radius:14px;
            background:#FFFFFF; border:1px solid var(--line); position:relative;
            box-shadow:0 6px 16px rgba(15,23,42,.05);
        }}
        .step .n {{
            display:inline-grid; place-items:center; width:22px; height:22px; border-radius:50%;
            background:#E8EEFB; color:#5B6B86; font-size:11px; font-weight:950; margin-bottom:6px;
        }}
        .step .t {{ display:block; font-size:12.5px; font-weight:850; color:#5B6B86; line-height:1.25; }}
        .step.done {{ border-color:#BBF7D0; background:#F0FDF4; }}
        .step.done .n {{ background:#16A34A; color:#FFFFFF; }}
        .step.done .t {{ color:#166534; }}
        .step.active {{
            border-color:{BRAND_BLUE}; background:#F4F8FF;
            box-shadow:0 0 0 1px #BFD4FF, 0 12px 26px rgba(35,103,255,.16);
        }}
        .step.active .n {{ background:{BRAND_BLUE}; color:#FFFFFF; }}
        .step.active .t {{ color:#0B1B46; }}

        /* ---------- cards ---------- */
        .card {{
            background:var(--card-bg); border:1px solid var(--line); border-radius:18px;
            padding:20px 22px; box-shadow:0 10px 26px rgba(15,23,42,.05); margin-bottom:16px;
        }}
        .card h3 {{ margin:0 0 4px; font-size:16px; font-weight:900; color:#0B1B46; }}
        .card p.sub {{ margin:0 0 14px; font-size:13px; color:var(--text-muted); font-weight:600; }}

        /* ---------- kpi ---------- */
        .kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(168px,1fr)); gap:12px; margin-bottom:18px; }}
        .kpi {{
            background:#FFFFFF; border:1px solid var(--line); border-radius:16px; padding:16px 18px;
            box-shadow:0 8px 20px rgba(15,23,42,.05);
        }}
        .kpi .lbl {{ font-size:11px; font-weight:900; letter-spacing:.1em; text-transform:uppercase; color:var(--text-muted); }}
        .kpi .val {{ margin-top:6px; font-size:26px; font-weight:950; color:#0B1B46; line-height:1.05; }}
        .kpi .fnt {{ margin-top:4px; font-size:12px; color:var(--text-muted); font-weight:650; }}
        .kpi.accent {{ background:linear-gradient(140deg,#F2F6FF, #FFFFFF); border-color:#C9DAFF; }}

        /* ---------- file slots ---------- */
        .slot {{
            display:flex; align-items:center; gap:12px; padding:11px 14px; border-radius:13px;
            border:1px solid var(--line); background:#FFFFFF; margin-bottom:8px;
        }}
        .slot .idx {{
            width:26px; height:26px; border-radius:8px; display:grid; place-items:center;
            background:#EEF3FF; color:{BRAND_PRIMARY}; font-size:11px; font-weight:950; flex:0 0 auto;
        }}
        .slot .meta {{ flex:1 1 auto; min-width:0; }}
        .slot .meta b {{ display:block; font-size:13px; color:#0B1B46; font-weight:850; }}
        .slot .meta span {{ display:block; font-size:11.5px; color:var(--text-muted); font-weight:650;
                            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .slot .pill {{ font-size:11px; font-weight:900; padding:4px 10px; border-radius:999px; flex:0 0 auto; }}
        .pill-ok {{ background:#E7F7EE; color:#0B7A3B; }}
        .pill-wait {{ background:#F1F5F9; color:#64748B; }}
        .pill-err {{ background:#FEE2E2; color:#B91C1C; }}

        /* ---------- medidor ---------- */
        .gauge-card {{
            background:#FFFFFF; border:1px solid var(--line); border-radius:18px;
            padding:14px 18px 18px; box-shadow:0 10px 26px rgba(15,23,42,.05);
        }}
        .gauge-txt {{ text-align:center; margin-top:-6px; }}
        .gauge-txt b {{ display:block; font-size:14px; font-weight:900; color:#0B1B46; }}
        .gauge-txt span {{ display:block; font-size:12px; color:var(--text-muted); font-weight:650; }}

        /* ---------- tabla mini ---------- */
        table.mini {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
        table.mini th {{
            text-align:left; padding:7px 10px; background:#F3F6FB; color:#0B1B46;
            font-weight:900; border-bottom:1px solid var(--line);
        }}
        table.mini td {{
            padding:7px 10px; border-bottom:1px solid #F1F5F9; color:#334155; vertical-align:top;
        }}
        table.mini tr:last-child td {{ border-bottom:none; }}

        /* ---------- issues ---------- */
        .issue {{
            border-radius:14px; padding:13px 16px; margin-bottom:9px; border:1px solid;
            display:flex; gap:12px; align-items:flex-start;
        }}
        .issue .ic {{ font-size:15px; line-height:1.3; }}
        .issue b {{ display:block; font-size:13.5px; font-weight:900; margin-bottom:2px; }}
        .issue span {{ font-size:12.5px; font-weight:600; line-height:1.5; }}
        .issue-error {{ background:#FEF2F2; border-color:#FECACA; color:#991B1B; }}
        .issue-warn  {{ background:#FFFBEB; border-color:#FDE68A; color:#92400E; }}
        .issue-info  {{ background:#F0F7FF; border-color:#BFDBFE; color:#1E40AF; }}
        .issue-ok    {{ background:#F0FDF4; border-color:#BBF7D0; color:#166534; }}

        /* ---------- controles ---------- */
        div[data-testid="stFileUploader"] section {{
            border-radius:14px; border:1.5px dashed #BFD4FF; background:#FAFCFF;
        }}
        .stButton button, button[data-testid^="stBaseButton"] {{
            border-radius:12px; font-weight:850;
        }}
        .stButton button[kind="primary"] {{
            background:{BRAND_BLUE}; border-color:{BRAND_BLUE};
        }}
        .stDownloadButton button {{
            border-radius:14px; min-height:54px; font-weight:950; font-size:15px;
            background:linear-gradient(135deg,#0B7A3B,#16A34A); border:none; color:#FFF;
        }}
        div[data-testid="stDataFrame"] {{ border-radius:14px; overflow:hidden; border:1px solid var(--line); }}

        /* ---------- tabs tipo pill ----------
           Streamlit cambio de BaseWeb a react-aria segun la version, asi que se
           apuntan las dos estructuras. */
        .stTabs [data-baseweb="tab-list"],
        div[data-testid="stTabs"] [role="tablist"] {{
            gap:6px !important; background:#EDF1F8 !important; padding:5px !important;
            border-radius:14px !important; border:1px solid var(--line) !important;
            margin-bottom:18px !important; display:flex !important; flex-wrap:wrap;
        }}
        .stTabs [data-baseweb="tab-highlight"],
        .stTabs [data-baseweb="tab-border"],
        div[data-testid="stTabs"] [data-testid="stTabHighlight"] {{ display:none !important; }}
        .stTabs [data-baseweb="tab"],
        div[data-testid="stTabs"] [role="tab"] {{
            border-radius:10px; font-weight:800; font-size:13px; color:#5B6B86;
            padding:9px 16px; background:transparent; border:none;
            transition:background .15s, color .15s, box-shadow .15s;
        }}
        .stTabs [data-baseweb="tab"] p,
        div[data-testid="stTabs"] [role="tab"] p {{
            font-weight:800; font-size:13px; margin:0;
        }}
        .stTabs [data-baseweb="tab"]:hover,
        div[data-testid="stTabs"] [role="tab"]:hover {{ background:#FFFFFF; color:#0B1B46; }}
        .stTabs [aria-selected="true"],
        div[data-testid="stTabs"] [role="tab"][aria-selected="true"],
        div[data-testid="stTabs"] [role="tab"][data-selected] {{
            background:#FFFFFF !important; color:#0B1B46 !important;
            box-shadow:0 3px 10px rgba(15,23,42,.09);
        }}
        .stTabs [data-baseweb="tab-panel"],
        div[data-testid="stTabs"] [role="tabpanel"] {{ padding-top:2px; }}

        /* ---------- encabezado de seccion ---------- */
        .sec-head {{ display:flex; align-items:center; gap:12px; margin:4px 0 14px; }}
        .sec-ico {{
            width:38px; height:38px; flex:0 0 auto; border-radius:12px; display:grid;
            place-items:center; background:#EEF3FF; color:{BRAND_PRIMARY};
        }}
        .sec-txt b {{ display:block; font-size:16px; font-weight:900; color:#0B1B46; line-height:1.2; }}
        .sec-txt span {{ display:block; font-size:12.5px; color:var(--text-muted); font-weight:620; }}

        /* ---------- tarjetas de acceso (inicio) ---------- */
        .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:14px; }}
        .tile {{
            background:#FFFFFF; border:1px solid var(--line); border-radius:18px; padding:20px;
            box-shadow:0 8px 22px rgba(15,23,42,.05); position:relative; overflow:hidden;
        }}
        .tile .t-ico {{
            width:42px; height:42px; border-radius:13px; display:grid; place-items:center;
            background:#EEF3FF; color:{BRAND_PRIMARY}; margin-bottom:13px;
        }}
        .tile b {{ display:block; font-size:15px; font-weight:900; color:#0B1B46; }}
        .tile p {{ margin:5px 0 0; font-size:12.5px; color:var(--text-muted);
                   font-weight:620; line-height:1.55; }}
        .tile .t-step {{
            display:inline-flex; align-items:center; gap:5px; margin-top:12px;
            font-size:11.5px; font-weight:850; color:{BRAND_BLUE};
        }}

        /* ---------- chips de estado ---------- */
        .chips {{ display:flex; flex-wrap:wrap; gap:7px; margin:2px 0 14px; }}
        .chip {{
            display:inline-flex; align-items:center; gap:6px; padding:6px 12px;
            border-radius:999px; font-size:11.5px; font-weight:800; border:1px solid;
        }}
        .chip-ok {{ background:#E7F7EE; border-color:#BBF7D0; color:#0B7A3B; }}
        .chip-warn {{ background:#FFFBEB; border-color:#FDE68A; color:#92400E; }}
        .chip-err {{ background:#FEE2E2; border-color:#FECACA; color:#B91C1C; }}
        .chip-idle {{ background:#F1F5F9; border-color:#E2E8F0; color:#64748B; }}

        /* ---------- estados de la navegacion ---------- */
        {_css_nav()}
        </style>
        """,
        unsafe_allow_html=True,
    )


#: Modulos principales del sidebar: clave -> (etiqueta, descripcion, icono).
MODULOS = {
    "inicio": ("Inicio", "Resumen y accesos", "home"),
    "repo": ("Tabla de Repo", "Reposicion semanal", "table"),
    "llenado": ("Llenados de Canal", "Reparto de OC", "truck"),
    "efectividad": ("Analisis de Efectividad", "Resultado de traspasos", "chart"),
    "pedidos": ("Dashboard de Pedidos", "Pedido contra despachado", "package"),
}


def nav(actual: str, state_key: str = "modulo") -> str:
    """Navegacion lateral con tarjetas.

    El boton **es** la tarjeta: se estiliza el control nativo en vez de taparlo
    con un HTML encima. Superponer un boton invisible no funciona, porque
    Streamlit no le da al wrapper el tamano de la tarjeta y el clic cae fuera.

    El icono entra por `::before` como imagen de fondo y la descripcion por
    `::after`, que es lo unico que se puede inyectar dentro de un boton.
    """
    # El estado va en la CLAVE del widget, no en un <style> que se reescribe.
    # Si se cambia el texto del bloque de estilos, el navegador actualiza el
    # fondo del boton pero no vuelve a calcular su ::before, y el icono se
    # queda con el color del modulo anterior. Con una clase distinta por estado
    # el elemento es nuevo y el pseudo-elemento se recalcula solo.
    for clave, (etiqueta, _desc, _ico) in MODULOS.items():
        sufijo = "on" if clave == actual else "off"
        if st.sidebar.button(etiqueta, key=f"nav_{clave}_{sufijo}", width="stretch"):
            if st.session_state.get(state_key) != clave:
                st.session_state[state_key] = clave
                st.rerun()
    return st.session_state.get(state_key, actual)


def _css_nav() -> str:
    """Reglas por modulo y estado. Son fijas, se emiten una sola vez."""
    from .icons import icon_data_uri

    partes = []
    for clave, (_etiqueta, desc, ico) in MODULOS.items():
        for sufijo, activo in (("on", True), ("off", False)):
            sel = f'section[data-testid="stSidebar"] div.st-key-nav_{clave}_{sufijo} button'
            partes.append(f"""
            {sel} {{
                background:{'linear-gradient(120deg,#EEF3FF,#FFFFFF)' if activo else 'transparent'};
                border-color:{'#C9DAFF' if activo else 'transparent'};
                box-shadow:{'0 6px 18px rgba(35,103,255,.13)' if activo else 'none'};
            }}
            {sel}::before {{
                background-color:{BRAND_BLUE if activo else '#E9EFFB'};
                background-image:url("{icon_data_uri(ico, '#FFFFFF' if activo else '#5B6B86')}");
            }}
            {sel}::after {{
                content:"{escape(desc)}";
                color:{'#5B7CC4' if activo else '#93A3BC'};
            }}
            {sel} p {{
                color:{'#0B1B46' if activo else '#33415A'};
                font-weight:{900 if activo else 850};
            }}""")
    return "".join(partes)


def sidebar_section(titulo: str) -> None:
    html(f'<div class="sb-sec">{escape(titulo)}</div>', sidebar=True)


def sidebar_footer(usuario: str) -> None:
    html(f'<div class="sb-foot">{icon("shield", 13)}<span>{escape(usuario)}</span></div>',
         sidebar=True)


def sidebar_brand(subtitle: str = "") -> None:
    """Cabecera del sidebar con el logo de Forus."""
    src = image_data_uri(ASSETS / "forus_logo.png")
    logo = (f'<img src="{src}" alt="FORUS">' if src
            else '<div class="sb-fallback">FORUS</div>')
    html(f"""
    <div class="sb-brand">
        <div class="sb-logo">{logo}</div>
        <div class="sb-txt">
            <b>Repo Control Center</b>
            <span>{escape(subtitle)}</span>
        </div>
    </div>
    """, sidebar=True)


def hero(title: str, subtitle: str, eyebrow: str = "Planeamiento y reposicion") -> None:
    html(f"""
    <div class="hero">
        <span class="eyebrow">{escape(eyebrow)}</span>
        <h1>{escape(title)}</h1>
        <p>{escape(subtitle)}</p>
    </div>
    """)


def stepper(steps: list[str], current: int) -> None:
    parts = []
    for i, name in enumerate(steps, start=1):
        cls = "done" if i < current else ("active" if i == current else "")
        mark = "✓" if i < current else str(i)
        parts.append(f'<div class="step {cls}"><span class="n">{mark}</span>'
                     f'<span class="t">{escape(name)}</span></div>')
    html(f'<div class="stepper">{"".join(parts)}</div>')


def kpi_row(items: list[tuple[str, str, str]], accent_first: bool = True) -> None:
    cells = []
    for i, (label, value, footnote) in enumerate(items):
        cls = "kpi accent" if (accent_first and i == 0) else "kpi"
        cells.append(f'<div class="{cls}"><div class="lbl">{escape(label)}</div>'
                     f'<div class="val">{escape(value)}</div>'
                     f'<div class="fnt">{escape(footnote)}</div></div>')
    html(f'<div class="kpis">{"".join(cells)}</div>')


def issue_box(severity: str, title: str, detail: str) -> None:
    nombres = {"error": "x-circle", "warn": "alert", "info": "info", "ok": "check-circle"}
    html(f'<div class="issue issue-{severity}">'
         f'<span class="ic">{icon(nombres.get(severity, "info"), 16)}</span>'
         f'<div><b>{escape(title)}</b><span>{escape(detail)}</span></div></div>')


def section(titulo: str, subtitulo: str = "", ico: str = "layers") -> None:
    """Encabezado de seccion con icono, para separar bloques dentro de una pagina."""
    html(f"""
    <div class="sec-head">
      <span class="sec-ico">{icon(ico, 19)}</span>
      <span class="sec-txt"><b>{escape(titulo)}</b><span>{escape(subtitulo)}</span></span>
    </div>
    """)


def tiles(items: list[tuple[str, str, str, str]]) -> None:
    """Tarjetas de acceso: (icono, titulo, descripcion, pie)."""
    cajas = []
    for ico, titulo, desc, pie in items:
        pie_html = (f'<span class="t-step">{escape(pie)} {icon("arrow-right", 13)}</span>'
                    if pie else "")
        cajas.append(f'<div class="tile"><div class="t-ico">{icon(ico, 21)}</div>'
                     f'<b>{escape(titulo)}</b><p>{escape(desc)}</p>{pie_html}</div>')
    html(f'<div class="tiles">{"".join(cajas)}</div>')


def chips(items: list[tuple[str, str]]) -> None:
    """Chips de estado: (estado, texto) con estado ok|warn|err|idle."""
    nombres = {"ok": "check", "warn": "alert", "err": "x-circle", "idle": "clock"}
    partes = [f'<span class="chip chip-{estado}">{icon(nombres.get(estado, "info"), 13)}'
              f'{escape(texto)}</span>' for estado, texto in items]
    html(f'<div class="chips">{"".join(partes)}</div>')


def slot_row(idx: str, label: str, detail: str, state: str) -> None:
    pill = {"ok": ("pill-ok", "Listo"), "err": ("pill-err", "Revisar"), "wait": ("pill-wait", "Pendiente")}
    cls, text = pill.get(state, pill["wait"])
    html(f'<div class="slot"><span class="idx">{escape(idx)}</span>'
         f'<div class="meta"><b>{escape(label)}</b><span>{escape(detail)}</span></div>'
         f'<span class="pill {cls}">{text}</span></div>')
