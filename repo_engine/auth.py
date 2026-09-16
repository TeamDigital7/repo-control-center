"""Login con el mismo esquema que el Catalogo Control Center."""

from __future__ import annotations

import hmac

import streamlit as st

from .ui import ASSETS, html, image_data_uri, login_styles

#: No hay usuarios por defecto a proposito. Tener credenciales en el codigo
#: significa publicarlas: este repositorio es publico y su historial tambien.
#: Los usuarios viven solo en los secrets, que nunca se suben.


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def get_users() -> dict[str, str]:
    try:
        cfg = dict(st.secrets.get("app_auth", {}))
    except Exception:
        cfg = {}
    users = cfg.get("users")
    if users:
        return {_normalize(u): str(p) for u, p in dict(users).items() if _normalize(u) and p}
    user, password = _normalize(cfg.get("username", "")), str(cfg.get("password", ""))
    if user and password:
        return {user: password}
    return {}


def require_login() -> bool:
    if st.session_state.get("authenticated"):
        return True

    login_styles()
    forus_src = image_data_uri(ASSETS / "forus_logo.png")
    forus_logo = (
        f'<img src="{forus_src}" alt="FORUS">' if forus_src
        else '<div class="login-forus-fallback">FORUS<small>CONSUMER FANATIC</small></div>'
    )

    with st.container(key="login_card"):
        html(f"""
        <div class="login-head">
            <div class="login-logo-row">
                <div class="login-forus-logo">{forus_logo}</div>
                <div class="login-divider"></div>
                <div class="login-app-badge">📦</div>
            </div>
            <h1>Repo Control Center</h1>
            <p>Tabla de Repo Final automatizada</p>
        </div>
        """)
        _brand_strip()
        with st.container(key="login_form_area"):
            with st.form("login_form"):
                username = st.text_input("Correo electronico", placeholder="nombre.apellido@empresa.com")
                password = st.text_input("Contrasena", type="password", placeholder="********")
                submitted = st.form_submit_button("Ingresar", type="primary")
        html('<div class="login-note">Sistema exclusivo para personal autorizado</div>')

    html("""
    <div class="login-foot">
        <strong>Reposicion multimarca</strong>
        69 tiendas &bull; 15 marcas &bull; Area de Producto
    </div>
    """)

    if not get_users():
        st.error(
            "No hay usuarios configurados. Agrega el bloque [app_auth.users] a "
            "los secrets (en Streamlit Cloud: Settings -> Secrets) con una linea "
            "por persona. La app no trae usuarios por defecto: tenerlos en el "
            "codigo seria publicarlos."
        )
        return False

    if submitted:
        users = get_users()
        user = _normalize(username)
        expected = users.get(user)
        if expected and hmac.compare_digest(str(password), expected):
            st.session_state["authenticated"] = True
            st.session_state["auth_user"] = user
            st.rerun()
        st.error("Usuario o contrasena incorrectos.")
    return False


#: Marcas que se muestran en la franja del login, en orden.
BRAND_LOGOS = [
    ("Columbia", "logo_columbia.png"),
    ("Hush Puppies", "logo_hushpuppies.png"),
    ("Rockford", "logo_rockford.webp"),
    ("Vans", "logo_vans.jpg"),
    ("Patagonia", "logo_patagonia.png"),
    ("Keds", "logo_keds.png"),
    ("Mountain Hardwear", "logo_mhw.png"),
    ("Sorel", "logo_sorel.webp"),
]


def _brand_strip() -> None:
    chips = []
    for label, filename in BRAND_LOGOS:
        src = image_data_uri(ASSETS / "brands" / filename)
        if src:
            chips.append(f'<span class="brand-chip"><img src="{src}" alt="{label}"></span>')
    if chips:
        html(f'<div class="login-brands">{"".join(chips)}</div>')


def logout() -> None:
    for key in ("authenticated", "auth_user"):
        st.session_state.pop(key, None)
    st.rerun()
