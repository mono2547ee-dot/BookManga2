import base64
import hmac
import html
import time

import pandas as pd
import requests
import streamlit as st
from neo4j import GraphDatabase, RoutingControl

st.set_page_config(page_title="Manga Recommendation System", page_icon="📚",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
.hero {padding: 1.5rem; border-radius: 20px; color: white; margin-bottom: 1rem;
       background: linear-gradient(120deg, #111827 0%, #312e81 55%, #7c3aed 100%);}
.hero h1 {margin: 0; font-size: 2.2rem;}
.hero p {margin-top: .4rem; opacity: .9;}
.manga-card {padding: 1rem; border: 1px solid rgba(128,128,128,.3); border-radius: 16px;
             margin-bottom: .8rem; display: flex; gap: 1rem; align-items: flex-start;}
.manga-cover {width: 100px; height: 150px; object-fit: cover; border-radius: 8px;
              box-shadow: 0 2px 8px rgba(0,0,0,.3); flex-shrink: 0;}
.manga-info {flex: 1;}
.manga-info h3 {margin: .4rem 0 .2rem 0;}
.score {display: inline-block; padding: .25rem .6rem; border-radius: 999px;
        background: #7c3aed; color: white; font-size: .8rem; font-weight: bold;}
.muted {opacity: .7; font-size: .9rem;}
.reason {margin-top: .6rem; padding: .6rem .8rem; border-radius: 10px;
         background: rgba(124,58,237,.12); border-left: 4px solid #7c3aed; font-size: .92rem;}
</style>
""", unsafe_allow_html=True)

# =========================================================
# NEO4J
# =========================================================
@st.cache_resource(show_spinner=False)
def create_driver(uri, username, password):
    driver = GraphDatabase.driver(uri, auth=(username, password))
    driver.verify_connectivity()
    return driver


def get_connection():
    try:
        cfg = st.secrets["neo4j"]
        database = cfg.get("database", "308b65ad")
        return create_driver(cfg["uri"], cfg["username"], cfg["password"]), database
    except Exception as e:
        st.error("❌ เชื่อมต่อ Neo4j Aura ไม่สำเร็จ ตรวจสอบ Secrets")
        st.exception(e)
        st.stop()


driver, DATABASE = get_connection()


def run_query(cypher, parameters=None, write=False):
    result = driver.execute_query(
        cypher, parameters_=parameters or {}, database_=DATABASE,
        routing_=RoutingControl.WRITE if write else RoutingControl.READ)
    return [r.data() for r in result.records]


def create_constraints():
    run_query("CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE", write=True)
    run_query("CREATE CONSTRAINT manga_id_unique IF NOT EXISTS FOR (m:Manga) REQUIRE m.manga_id IS UNIQUE", write=True)

# =========================================================
# COVER IMAGES (ดึงรูปปกจาก MyAnimeList ผ่าน Jikan API)
# =========================================================
_svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='100' height='150'>"
        "<rect width='100' height='150' fill='#374151'/>"
        "<text x='50' y='80' fill='white' font-size='12' text-anchor='middle'>No Image</text></svg>")
PLACEHOLDER = "data:image/svg+xml;base64," + base64.b64encode(_svg.encode()).decode()


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_cover(title):
    try:
        r = requests.get("https://api.jikan.moe/v4/manga", timeout=10,
                         params={"q": title, "limit": 1, "order_by": "members", "sort": "desc"})
        data = r.json().get("data", [])
        if data:
            return data[0]["images"]["jpg"]["image_url"]
    except Exception:
        pass
    return ""

# =========================================================
# USER / MANGA / LIKES
# =========================================================
def get_users():
    return run_query("MATCH (u:User) RETURN u.user_id AS user_id, u.name AS name ORDER BY u.user_id")


def add_user(user_id, name):
    run_query("MERGE (u:User {user_id: $i}) SET u.name = $n", {"i": user_id, "n": name}, write=True)


def update_user(user_id, name):
    run_query("MATCH (u:User {user_id: $i}) SET u.name = $n", {"i": user_id, "n": name}, write=True)


def delete_user(user_id):
    run_query("MATCH (u:User {user_id: $i}) DETACH DELETE u", {"i": user_id}, write=True)


def get_mangas():
    return run_query("MATCH (m:Manga) RETURN m.manga_id AS manga_id, m.title AS title, "
                     "m.image_url AS image_url ORDER BY m.title")


def add_manga(manga_id, title, image_url=""):
    run_query("MERGE (m:Manga {manga_id: $i}) SET m.title = $t, m.image_url = $u",
              {"i": manga_id, "t": title, "u": image_url}, write=True)


def update_manga(manga_id, new_title=None, new_image_url=None):
    sets, params = [], {"i": manga_id}
    if new_title is not None:
        sets.append("m.title = $t"); params["t"] = new_title
    if new_image_url is not None:
        sets.append("m.image_url = $u"); params["u"] = new_image_url
    if sets:
        run_query(f"MATCH (m:Manga {{manga_id: $i}}) SET {', '.join(sets)}", params, write=True)


def delete_manga(manga_id):
    run_query("MATCH (m:Manga {manga_id: $i}) DETACH DELETE m", {"i": manga_id}, write=True)


def refresh_covers(only_missing=False):
    fetch_cover.clear()
    n = 0
    for m in get_mangas():
        if only_missing and m.get("image_url"):
            continue
        url = fetch_cover(m["title"])
        if url:
            update_manga(m["manga_id"], new_image_url=url)
            n += 1
        time.sleep(0.4)  # Jikan จำกัดจำนวน request ต่อวินาที
    return n


def get_liked_mangas(user_id):
    return run_query("MATCH (u:User {user_id: $i})-[:LIKES]->(m:Manga) RETURN m.manga_id AS manga_id, "
                     "m.title AS title, m.image_url AS image_url ORDER BY title", {"i": user_id})


def add_like(user_id, manga_id):
    run_query("MATCH (u:User {user_id: $u}), (m:Manga {manga_id: $m}) MERGE (u)-[:LIKES]->(m)",
              {"u": user_id, "m": manga_id}, write=True)


def delete_like(user_id, manga_id):
    run_query("MATCH (u:User {user_id: $u})-[r:LIKES]->(m:Manga {manga_id: $m}) DELETE r",
              {"u": user_id, "m": manga_id}, write=True)

# =========================================================
# RECOMMENDATION
# =========================================================
def recommend_by_similar_user(user_id, limit=5):
    return run_query("""
        MATCH (me:User {user_id: $user_id})-[:LIKES]->(liked:Manga)
              <-[:LIKES]-(similar:User)-[:LIKES]->(recommend:Manga)
        WHERE similar <> me AND NOT EXISTS { MATCH (me)-[:LIKES]->(recommend) }
        WITH recommend, count(DISTINCT similar) AS score,
             collect(DISTINCT liked.title) AS because,
             collect(DISTINCT similar.name) AS who
        RETURN recommend.manga_id AS manga_id, recommend.title AS title,
               recommend.image_url AS image_url, score, because, who,
               "similar_user" AS type
        ORDER BY score DESC, title
        LIMIT $limit
        """, {"user_id": user_id, "limit": int(limit)})


def recommend_popular(limit=5):
    return run_query("""
        MATCH (m:Manga)
        OPTIONAL MATCH (u:User)-[:LIKES]->(m)
        WITH m, count(u) AS score
        RETURN m.manga_id AS manga_id, m.title AS title, m.image_url AS image_url,
               score, "popular" AS type
        ORDER BY score DESC, title
        LIMIT $limit
        """, {"limit": int(limit)})


def get_recommendations(user_id, limit=5):
    if not get_liked_mangas(user_id):
        return recommend_popular(limit), "new_user"
    rows = recommend_by_similar_user(user_id, limit)
    if rows:
        return rows, "similar"
    return recommend_popular(limit), "popular_fallback"


def make_reason(row):
    """สร้างเหตุผลอัตโนมัติจากข้อมูลใน Graph"""
    if row.get("type") == "similar_user":
        because = ", ".join(row.get("because") or [])
        who = ", ".join((row.get("who") or [])[:3])
        return (f"เพราะคุณชอบ {because} และมีผู้ใช้ {row.get('score')} คน ({who}) "
                f"ที่ชอบเรื่องเดียวกับคุณ ก็ชอบเรื่องนี้ด้วย")
    if row.get("type") == "popular":
        return f"เป็นเรื่องยอดนิยม มีผู้กดชอบ {row.get('score')} คน"
    return "ผู้ดูแลระบบเลือกแนะนำให้"


def get_custom_reasons(user_id):
    rows = run_query("MATCH (:User {user_id: $i})-[r:RECOMMENDS]->(m:Manga) "
                     "WHERE r.custom_reason IS NOT NULL "
                     "RETURN m.manga_id AS manga_id, r.custom_reason AS reason", {"i": user_id})
    return {r["manga_id"]: r["reason"] for r in rows}


def save_custom_reason(user_id, manga_id, reason):
    run_query("""
        MATCH (u:User {user_id: $u}), (m:Manga {manga_id: $m})
        MERGE (u)-[r:RECOMMENDS]->(m)
        SET r.custom_reason = $reason, r.score = coalesce(r.score, 0), r.type = coalesce(r.type, "admin")
        """, {"u": user_id, "m": manga_id, "reason": reason}, write=True)


def remove_custom_reason(user_id, manga_id):
    run_query("MATCH (:User {user_id: $u})-[r:RECOMMENDS]->(:Manga {manga_id: $m}) "
              "REMOVE r.custom_reason", {"u": user_id, "m": manga_id}, write=True)


def get_all_custom_reasons():
    return run_query("MATCH (u:User)-[r:RECOMMENDS]->(m:Manga) WHERE r.custom_reason IS NOT NULL "
                     "RETURN u.user_id AS user_id, u.name AS user, m.manga_id AS manga_id, "
                     "m.title AS manga, r.custom_reason AS reason ORDER BY user_id")


def clear_recommend_relationships(user_id=None):
    # ไม่ลบเส้นที่ Admin เขียนเหตุผลไว้เอง
    if user_id:
        run_query("MATCH (u:User {user_id: $i})-[r:RECOMMENDS]->() WHERE r.custom_reason IS NULL DELETE r",
                  {"i": user_id}, write=True)
    else:
        run_query("MATCH ()-[r:RECOMMENDS]->() WHERE r.custom_reason IS NULL DELETE r", write=True)


def create_recommend_relationships(user_id=None, limit=5):
    clear_recommend_relationships(user_id)
    targets = [{"user_id": user_id}] if user_id else get_users()
    created = 0
    for user in targets:
        rows, _ = get_recommendations(user["user_id"], limit)
        for row in rows:
            run_query("""
                MATCH (u:User {user_id: $u}), (m:Manga {manga_id: $m})
                MERGE (u)-[r:RECOMMENDS]->(m)
                SET r.score = $score, r.type = $type, r.auto_reason = $reason
                """, {"u": user["user_id"], "m": row["manga_id"], "score": row["score"],
                      "type": row["type"], "reason": make_reason(row)}, write=True)
            created += 1
    return created


def get_recommends(user_id):
    return run_query("""
        MATCH (u:User {user_id: $i})-[r:RECOMMENDS]->(m:Manga)
        RETURN m.manga_id AS manga_id, m.title AS title, m.image_url AS image_url,
               r.score AS score, r.type AS type,
               r.custom_reason AS custom_reason, r.auto_reason AS auto_reason
        ORDER BY score DESC, title
        """, {"i": user_id})


def search_manga(keyword=""):
    return run_query("""
        MATCH (m:Manga)
        WHERE $k = "" OR toLower(m.title) CONTAINS toLower($k)
        OPTIONAL MATCH (u:User)-[:LIKES]->(m)
        RETURN m.manga_id AS manga_id, m.title AS title, m.image_url AS image_url, count(u) AS likes
        ORDER BY likes DESC, title
        """, {"k": keyword.strip()})


def get_graph(user_id=None):
    where = "{user_id: $i}" if user_id else ""
    tail = "" if user_id else "LIMIT 100"
    return run_query(f"""
        MATCH (u:User {where})-[r:LIKES|RECOMMENDS]->(m:Manga)
        RETURN u.user_id AS source_id, u.name AS source_name, type(r) AS relationship,
               m.manga_id AS target_id, m.title AS target_name {tail}
        """, {"i": user_id})


def get_metrics():
    q = lambda c: run_query(c)[0]["count"]
    return (q("MATCH (u:User) RETURN count(u) AS count"),
            q("MATCH (m:Manga) RETURN count(m) AS count"),
            q("MATCH ()-[r:LIKES]->() RETURN count(r) AS count"),
            q("MATCH ()-[r:RECOMMENDS]->() RETURN count(r) AS count"))

# =========================================================
# DEMO DATA
# =========================================================
def create_demo_data():
    create_constraints()
    names = ["Sompong", "Siriporn", "Niran", "Malee", "Chaiwat", "Kanya",
             "Anan", "Somying", "Prasit", "Nattaya", "New User"]
    users = [{"user_id": f"U{i+1:03d}", "name": n} for i, n in enumerate(names)]
    titles = ["Naruto", "One Piece", "Attack on Titan", "Demon Slayer", "Death Note",
              "My Hero Academia", "Jujutsu Kaisen", "Fullmetal Alchemist", "Spy x Family", "Chainsaw Man"]
    mangas = [{"manga_id": f"M{i+1:03d}", "title": t, "image_url": ""} for i, t in enumerate(titles)]
    likes = [["U001", "M001"], ["U001", "M002"], ["U002", "M009"], ["U002", "M004"],
             ["U003", "M001"], ["U003", "M002"], ["U003", "M007"], ["U004", "M009"],
             ["U004", "M004"], ["U004", "M006"], ["U005", "M005"], ["U005", "M003"],
             ["U006", "M005"], ["U006", "M003"], ["U006", "M008"], ["U007", "M001"],
             ["U007", "M006"], ["U008", "M007"], ["U008", "M010"], ["U009", "M005"],
             ["U009", "M010"], ["U010", "M002"], ["U010", "M008"]]
    run_query("UNWIND $r AS row MERGE (u:User {user_id: row.user_id}) SET u.name = row.name",
              {"r": users}, write=True)
    run_query("UNWIND $r AS row MERGE (m:Manga {manga_id: row.manga_id}) SET m.title = row.title, "
              "m.image_url = row.image_url", {"r": mangas}, write=True)
    run_query("UNWIND $r AS row MATCH (u:User {user_id: row[0]}), (m:Manga {manga_id: row[1]}) "
              "MERGE (u)-[:LIKES]->(m)", {"r": likes}, write=True)
    refresh_covers()

# =========================================================
# UI HELPERS
# =========================================================
def display_manga_card(manga_id, title, image_url=None, score=None, rank=None, reason=None):
    img = image_url or fetch_cover(title) or PLACEHOLDER
    badge = ""
    if rank is not None:
        badge = f'<span class="score">#{rank} · score {score}</span>'
    elif score is not None:
        badge = f'<span class="score">score {score}</span>'
    reason_html = (f'<div class="reason">💡 <b>เหตุผลที่แนะนำ:</b> {html.escape(str(reason))}</div>'
                   if reason else "")
    # สำคัญ: HTML ต้องไม่มีบรรทัดที่ย่อหน้า ไม่งั้น Markdown จะมองเป็น code block
    card = (
        '<div class="manga-card">'
        f'<img src="{html.escape(img, quote=True)}" class="manga-cover" referrerpolicy="no-referrer" '
        f'onerror="this.onerror=null;this.src=\'{PLACEHOLDER}\'">'
        '<div class="manga-info">'
        f'{badge}<h3>{html.escape(str(title or ""))}</h3>'
        f'<div class="muted">Manga ID: {html.escape(str(manga_id))}</div>'
        f'{reason_html}</div></div>'
    )
    st.markdown(card, unsafe_allow_html=True)


def user_picker(label="เลือก User", key=None, include_all=False):
    users = get_users()
    if not users:
        st.warning("ยังไม่มี User")
        st.stop()
    opts = {"ทั้งหมด": None} if include_all else {}
    opts.update({f"{u['user_id']} — {u['name']}": u["user_id"] for u in users})
    return opts[st.selectbox(label, list(opts.keys()), key=key)]


def admin_gate():
    """ต้องตั้ง [admin] password ใน Streamlit Secrets ก่อนถึงจะเข้าหน้า Admin ได้"""
    pw = st.secrets.get("admin", {}).get("password")
    if not pw:
        st.error("ยังไม่ได้ตั้งรหัสผ่าน Admin ใน Secrets")
        st.code('[admin]\npassword = "ตั้งรหัสของคุณที่นี่"', language="toml")
        return False
    if st.session_state.get("admin_ok"):
        return True
    entered = st.text_input("🔐 รหัสผ่าน Admin", type="password")
    if st.button("เข้าสู่ระบบ", type="primary"):
        if hmac.compare_digest(entered, str(pw)):
            st.session_state["admin_ok"] = True
            st.rerun()
        else:
            st.error("รหัสผ่านไม่ถูกต้อง")
    return False

# =========================================================
# SIDEBAR + HEADER
# =========================================================
with st.sidebar:
    st.markdown("## 📚 MangaGraph")
    st.caption("Neo4j Aura + Streamlit")
    page = st.radio("เมนู", ["Dashboard", "Recommendations", "Manga Search",
                             "Manage Likes", "Graph Explorer", "Admin Panel"])
    st.divider()
    st.caption("Manga Recommendation System")

st.markdown('<div class="hero"><h1>📚 Manga Recommendation System</h1>'
            '<p>ระบบแนะนำ Manga ด้วย Neo4j Graph Database</p></div>', unsafe_allow_html=True)

# =========================================================
# DASHBOARD
# =========================================================
if page == "Dashboard":
    st.subheader("📊 ภาพรวมระบบ")
    users_c, manga_c, likes_c, rec_c = get_metrics()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Users", users_c); c2.metric("Manga", manga_c)
    c3.metric("LIKES", likes_c); c4.metric("RECOMMENDS", rec_c)
    st.divider()
    user_id = user_picker()
    left, right = st.columns(2)
    with left:
        st.markdown("### ❤️ Manga ที่ User ชอบ")
        rows = get_liked_mangas(user_id)
        for row in rows:
            display_manga_card(row["manga_id"], row["title"], row.get("image_url"))
        if not rows:
            st.info("User นี้ยังไม่มี LIKES")
    with right:
        st.markdown("### ✨ Manga ที่ระบบแนะนำ")
        rows = get_recommends(user_id)
        for i, row in enumerate(rows, start=1):
            reason = row.get("custom_reason") or row.get("auto_reason") or "—"
            display_manga_card(row["manga_id"], row["title"], row.get("image_url"),
                               score=row.get("score"), rank=i, reason=reason)
        if not rows:
            st.info("ยังไม่มี RECOMMENDS (ไปที่หน้า Recommendations แล้วกดสร้างเส้น RECOMMENDS)")

# =========================================================
# RECOMMENDATIONS
# =========================================================
elif page == "Recommendations":
    st.subheader("✨ Manga Recommendation")
    user_id = user_picker()
    limit = st.slider("จำนวน Manga ที่แนะนำ", 3, 12, 5)
    rows, mode = get_recommendations(user_id, limit)
    if mode == "similar":
        st.success("👥 พบ User ที่ความชอบคล้ายกัน จึงใช้ Similar User Recommendation")
    elif mode == "new_user":
        st.info("🆕 User นี้ยังไม่มี LIKES จึงใช้ Popular Manga Recommendation")
    else:
        st.info("ไม่พบ User ที่ความชอบคล้ายกัน จึงใช้ Popular Manga แทน")
    custom = get_custom_reasons(user_id)
    for i, row in enumerate(rows, start=1):
        reason = custom.get(row["manga_id"]) or make_reason(row)
        display_manga_card(row["manga_id"], row["title"], row.get("image_url"),
                           score=row["score"], rank=i, reason=reason)
    if not rows:
        st.warning("ยังไม่มี Manga สำหรับแนะนำ")
    st.divider()
    if st.button("🔗 สร้างเส้น RECOMMENDS ให้ User นี้", type="primary", use_container_width=True):
        st.success(f"สร้าง RECOMMENDS สำเร็จ {create_recommend_relationships(user_id, limit)} เส้น")
        st.rerun()

# =========================================================
# MANGA SEARCH
# =========================================================
elif page == "Manga Search":
    st.subheader("🔎 ค้นหา Manga")
    keyword = st.text_input("ชื่อ Manga", placeholder="เช่น Naruto, One Piece, Jujutsu")
    rows = search_manga(keyword)
    st.write(f"พบ {len(rows)} รายการ")
    for row in rows:
        display_manga_card(row["manga_id"], row["title"], row.get("image_url"))
        st.caption(f"จำนวน Likes: {row['likes']}")
    if not rows:
        st.info("ไม่พบ Manga")

# =========================================================
# MANAGE LIKES
# =========================================================
elif page == "Manage Likes":
    st.subheader("❤️ จัดการ Manga ที่ User ชอบ")
    all_mangas = get_mangas()
    if not all_mangas:
        st.warning("ยังไม่มี Manga"); st.stop()
    user_id = user_picker()
    st.markdown("### ❤️ Manga ที่ชอบอยู่แล้ว")
    liked = get_liked_mangas(user_id)
    for row in liked:
        c1, c2 = st.columns([4, 1])
        with c1:
            display_manga_card(row["manga_id"], row["title"], row.get("image_url"))
        with c2:
            st.write(""); st.write("")
            if st.button("❌ ลบ", key=f"remove_{user_id}_{row['manga_id']}"):
                delete_like(user_id, row["manga_id"])
                st.rerun()
    if not liked:
        st.info("User นี้ยังไม่มี LIKES")
    st.divider()
    mopts = {f"{m['manga_id']} — {m['title']}": m["manga_id"] for m in all_mangas}
    manga_id = mopts[st.selectbox("เลือก Manga ที่ชอบ", list(mopts.keys()))]
    if st.button("❤️ เพิ่ม LIKES", type="primary", use_container_width=True):
        add_like(user_id, manga_id)
        st.rerun()

# =========================================================
# GRAPH EXPLORER
# =========================================================
elif page == "Graph Explorer":
    st.subheader("🕸️ Graph Explorer")
    user_id = user_picker(include_all=True)
    rows = get_graph(user_id)
    if not rows:
        st.info("ยังไม่มี Graph")
    else:
        dot = ["digraph G {", 'rankdir="LR";',
               'node [shape=box, style="rounded,filled", fillcolor="#f8fafc"];']
        seen = set()
        for r in rows:
            for key, name_key, kind in (("source_id", "source_name", "User"),
                                        ("target_id", "target_name", "Manga")):
                if r[key] not in seen:
                    label = str(r[name_key]).replace('"', "'")
                    dot.append(f'"{r[key]}" [label="{label}\\n{kind}"];')
                    seen.add(r[key])
            dot.append(f'"{r["source_id"]}" -> "{r["target_id"]}" [label="{r["relationship"]}"];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot), use_container_width=True)
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.code("MATCH p=(u:User)-[r:LIKES|RECOMMENDS]->(m:Manga)\nRETURN p\nLIMIT 100", language="cypher")

# =========================================================
# ADMIN PANEL
# =========================================================
elif page == "Admin Panel":
    st.subheader("⚙️ Admin Panel")
    if not admin_gate():
        st.stop()
    if st.sidebar.button("🚪 ออกจากระบบ Admin"):
        st.session_state["admin_ok"] = False
        st.rerun()

    tabs = st.tabs(["👥 Users", "📚 Manga", "❤️ Likes", "💬 เหตุผลการแนะนำ", "🔄 รีเซ็ต"])

    # ---------- USERS ----------
    with tabs[0]:
        with st.container(border=True):
            st.markdown("### ➕ เพิ่ม User")
            c1, c2 = st.columns(2)
            uid = c1.text_input("User ID (เช่น U012)", key="new_uid")
            uname = c2.text_input("ชื่อ User", key="new_uname")
            if st.button("➕ เพิ่ม User"):
                if uid and uname:
                    add_user(uid.strip(), uname.strip()); st.rerun()
                else:
                    st.warning("กรุณากรอกข้อมูลให้ครบ")
        all_users = get_users()
        st.dataframe(pd.DataFrame(all_users), use_container_width=True, hide_index=True)
        if all_users:
            sel = st.selectbox("เลือก User เพื่อแก้ไข/ลบ",
                               [f"{u['user_id']} — {u['name']}" for u in all_users], key="edit_user_sel")
            sel_uid = sel.split(" — ")[0]
            cur = next(u["name"] for u in all_users if u["user_id"] == sel_uid)
            c1, c2 = st.columns(2)
            new_name = c1.text_input("แก้ไขชื่อ", value=cur, key=f"uname_{sel_uid}")
            if c1.button("💾 บันทึกชื่อ"):
                update_user(sel_uid, new_name); st.rerun()
            c2.write(""); c2.write("")
            if c2.button("🗑️ ลบ User (รวม LIKES/RECOMMENDS)"):
                delete_user(sel_uid); st.rerun()

    # ---------- MANGA ----------
    with tabs[1]:
        with st.container(border=True):
            st.markdown("### ➕ เพิ่ม Manga")
            c1, c2, c3 = st.columns(3)
            mid = c1.text_input("Manga ID (เช่น M011)", key="new_mid")
            mtitle = c2.text_input("ชื่อ Manga", key="new_mtitle")
            mimg = c3.text_input("URL รูปปก (เว้นว่าง = ดึงอัตโนมัติ)", key="new_mimg")
            if st.button("➕ เพิ่ม Manga"):
                if mid and mtitle:
                    add_manga(mid.strip(), mtitle.strip(), mimg.strip() or fetch_cover(mtitle.strip()))
                    st.rerun()
                else:
                    st.warning("กรุณากรอก Manga ID และชื่อ")
        with st.container(border=True):
            st.markdown("### 🖼️ ดึงรูปปกอัตโนมัติ (MyAnimeList)")
            c1, c2 = st.columns(2)
            if c1.button("เติมเฉพาะเรื่องที่ยังไม่มีรูป"):
                with st.spinner("กำลังดึงรูปปก..."):
                    st.success(f"อัปเดตรูปแล้ว {refresh_covers(only_missing=True)} เรื่อง")
            if c2.button("ดึงรูปใหม่ทั้งหมด (แก้รูปเสีย)", type="primary"):
                with st.spinner("กำลังดึงรูปปก..."):
                    st.success(f"อัปเดตรูปแล้ว {refresh_covers()} เรื่อง")
        all_mangas = get_mangas()
        st.dataframe(pd.DataFrame(all_mangas), use_container_width=True, hide_index=True)
        if all_mangas:
            sel = st.selectbox("เลือก Manga เพื่อแก้ไข/ลบ",
                               [f"{m['manga_id']} — {m['title']}" for m in all_mangas], key="edit_manga_sel")
            sel_mid = sel.split(" — ")[0]
            cur = next(m for m in all_mangas if m["manga_id"] == sel_mid)
            c1, c2, c3 = st.columns(3)
            nt = c1.text_input("แก้ไขชื่อ", value=cur.get("title") or "", key=f"mt_{sel_mid}")
            if c1.button("💾 บันทึกชื่อ", key="save_mt"):
                update_manga(sel_mid, new_title=nt); st.rerun()
            ni = c2.text_input("URL รูปปก", value=cur.get("image_url") or "", key=f"mi_{sel_mid}")
            if c2.button("💾 บันทึกรูป", key="save_mi"):
                update_manga(sel_mid, new_image_url=ni); st.rerun()
            c3.write(""); c3.write("")
            if c3.button("🗑️ ลบ Manga", key="del_manga"):
                delete_manga(sel_mid); st.rerun()

    # ---------- LIKES ----------
    with tabs[2]:
        all_users, all_mangas = get_users(), get_mangas()
        if all_users and all_mangas:
            with st.container(border=True):
                st.markdown("### ➕ เพิ่ม Like")
                c1, c2 = st.columns(2)
                lu = c1.selectbox("User", [f"{u['user_id']} — {u['name']}" for u in all_users], key="lu")
                lm = c2.selectbox("Manga", [f"{m['manga_id']} — {m['title']}" for m in all_mangas], key="lm")
                if st.button("➕ เพิ่ม Like"):
                    add_like(lu.split(" — ")[0], lm.split(" — ")[0]); st.rerun()
        likes_data = [{"User ID": u["user_id"], "User Name": u["name"],
                       "Manga ID": r["manga_id"], "Manga Title": r["title"]}
                      for u in all_users for r in get_liked_mangas(u["user_id"])]
        st.dataframe(pd.DataFrame(likes_data), use_container_width=True, hide_index=True)
        if likes_data:
            labels = [f"{l['User ID']} ({l['User Name']}) → {l['Manga ID']} ({l['Manga Title']})"
                      for l in likes_data]
            chosen = st.selectbox("เลือก Like ที่ต้องการลบ", labels, key="del_like_sel")
            t = likes_data[labels.index(chosen)]
            if st.button("🗑️ ลบ Like ที่เลือก"):
                delete_like(t["User ID"], t["Manga ID"]); st.rerun()

    # ---------- REASONS ----------
    with tabs[3]:
        st.markdown("### 💬 เขียนเหตุผลว่าทำไมแนะนำเรื่องนี้ให้ User คนนี้")
        st.caption("เหตุผลที่เขียนที่นี่จะแสดงแทนเหตุผลอัตโนมัติ และไม่ถูกลบเมื่อกดสร้างเส้น RECOMMENDS ใหม่")
        all_mangas = get_mangas()
        if all_mangas:
            ruid = user_picker("User ที่จะรับคำแนะนำ", key="reason_user")
            mopts = {f"{m['manga_id']} — {m['title']}": m["manga_id"] for m in all_mangas}
            rmid = mopts[st.selectbox("Manga ที่แนะนำ", list(mopts.keys()), key="reason_manga")]
            existing = get_custom_reasons(ruid).get(rmid, "")
            text = st.text_area("เหตุผล", value=existing, key=f"reason_{ruid}_{rmid}", height=120,
                                placeholder="เช่น User ชอบแนวต่อสู้ผจญภัย เรื่องนี้มีเนื้อเรื่องคล้าย Naruto")
            c1, c2 = st.columns(2)
            if c1.button("💾 บันทึกเหตุผล", type="primary"):
                if text.strip():
                    save_custom_reason(ruid, rmid, text.strip())
                    st.success("บันทึกเหตุผลแล้ว"); st.rerun()
                else:
                    st.warning("กรุณาพิมพ์เหตุผล")
            if existing and c2.button("🗑️ ลบเหตุผลนี้"):
                remove_custom_reason(ruid, rmid); st.rerun()
        st.markdown("#### 📋 เหตุผลที่บันทึกไว้ทั้งหมด")
        data = get_all_custom_reasons()
        if data:
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else:
            st.info("ยังไม่มีเหตุผลที่ Admin เขียนไว้")

    # ---------- RESET ----------
    with tabs[4]:
        st.warning("⚠️ การรีเซ็ตจะลบข้อมูลทั้งหมดใน Neo4j (Users, Manga, Likes, Recommends)")
        confirm = st.checkbox("ฉันยืนยันว่าต้องการลบข้อมูลทั้งหมด")
        if st.button("🗑️ ลบข้อมูลทั้งหมด", type="primary", disabled=not confirm):
            run_query("MATCH (n) DETACH DELETE n", write=True)
            st.success("ลบข้อมูลทั้งหมดสำเร็จ"); st.rerun()
        st.divider()
        st.caption("สร้าง User + Manga + LIKES (U011 ไม่มี LIKES เพื่อทดสอบ Cold Start) พร้อมดึงรูปปกอัตโนมัติ")
        if st.button("📦 สร้างข้อมูลตัวอย่าง", type="primary", use_container_width=True):
            with st.spinner("กำลังสร้างข้อมูลและดึงรูปปก..."):
                create_demo_data()
            st.success("สร้างข้อมูลตัวอย่างสำเร็จ"); st.rerun()
