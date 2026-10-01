import base64
import hmac
import os
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
def _fetch_cover_cached(title):
    # ถ้าหาไม่เจอจะ raise เพื่อไม่ให้ Streamlit จำผลลัพธ์ว่าง
    try:  # 1) AniList
        q = "query($s:String){Media(search:$s,type:MANGA,sort:SEARCH_MATCH){coverImage{large}}}"
        r = requests.post("https://graphql.anilist.co", timeout=10,
                          json={"query": q, "variables": {"s": title}})
        url = r.json()["data"]["Media"]["coverImage"]["large"]
        if url:
            return url
    except Exception:
        pass
    try:  # 2) Jikan (MyAnimeList)
        r = requests.get("https://api.jikan.moe/v4/manga", timeout=10,
                         params={"q": title, "limit": 1, "order_by": "members", "sort": "desc"})
        data = r.json().get("data", [])
        if data:
            return data[0]["images"]["jpg"]["image_url"]
    except Exception:
        pass
    raise ValueError("cover not found")


def fetch_cover(title):
    try:
        return _fetch_cover_cached(title)
    except Exception:
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
    _fetch_cover_cached.clear()
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
# รูปปกที่กำหนดเอง (ใช้แทนรูปที่ดึงอัตโนมัติ) key = Manga ID
COVER_OVERRIDES = {
    "M004": "data:image/jpeg;base64,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",  # Demon Slayer
}


def image_to_data_uri(uploaded_file):
    """แปลงไฟล์ที่อัปโหลดเป็น data URI เพื่อเก็บใน Neo4j"""
    mime = uploaded_file.type or "image/png"
    return f"data:{mime};base64," + base64.b64encode(uploaded_file.getvalue()).decode()


@st.cache_data(show_spinner=False)
def local_cover(manga_id):
    """รูปที่วางไว้ในโฟลเดอร์ covers/ ข้างไฟล์ app.py ตั้งชื่อตาม Manga ID เช่น covers/M004.png"""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "covers")
    for ext, mime in (("png", "image/png"), ("jpg", "image/jpeg"),
                      ("jpeg", "image/jpeg"), ("webp", "image/webp")):
        path = os.path.join(base, f"{manga_id}.{ext}")
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    return ""


def display_manga_card(manga_id, title, image_url=None, score=None, rank=None, reason=None):
    # ลำดับ: รูปในโฟลเดอร์ covers/ > รูปที่บันทึกในฐานข้อมูล > ดึงอัตโนมัติตามชื่อเรื่อง
    # (ลิงก์ wikimedia เก่าใช้ไม่ได้ จึงข้ามไป)
    img = COVER_OVERRIDES.get(str(manga_id)) or local_cover(str(manga_id))
    if not img and image_url and "wikimedia" not in image_url:
        img = image_url
    if not img:
        img = fetch_cover(str(title or "")) or PLACEHOLDER
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
        # คำนวณสดทุกครั้ง จึงมีเหตุผลให้ทุก User (รวม User ใหม่ที่ยังไม่มี LIKES)
        rows, _mode = get_recommendations(user_id, 5)
        custom = get_custom_reasons(user_id)
        for i, row in enumerate(rows, start=1):
            reason = custom.get(row["manga_id"]) or make_reason(row)
            display_manga_card(row["manga_id"], row["title"], row.get("image_url"),
                               score=row.get("score"), rank=i, reason=reason)
        if not rows:
            st.info("ยังไม่มี Manga สำหรับแนะนำ")
    if st.button("🔗 สร้างเส้น RECOMMENDS ให้ทุก User", use_container_width=True):
        st.success(f"สร้าง RECOMMENDS สำเร็จ {create_recommend_relationships(None, 5)} เส้น")
        st.rerun()

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
            st.markdown("##### 🖼️ อัปโหลดรูปปกเอง (ใช้แทนรูปที่ระบบดึงมาผิด)")
            up = st.file_uploader("เลือกไฟล์รูป (jpg / png / webp)", type=["jpg", "jpeg", "png", "webp"],
                                  key=f"up_{sel_mid}")
            if up is not None:
                st.image(up, width=140)
                if st.button("💾 ใช้รูปนี้เป็นปก", type="primary", key=f"save_up_{sel_mid}"):
                    update_manga(sel_mid, new_image_url=image_to_data_uri(up))
                    st.success("บันทึกรูปปกแล้ว"); st.rerun()

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
