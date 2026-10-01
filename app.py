import streamlit as st
import pandas as pd
from neo4j import GraphDatabase, RoutingControl

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Manga Recommendation System",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# CSS (แก้ไข: ลบ dedent() ออก)
# =========================================================
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }
    .hero {
        padding: 1.5rem;
        border-radius: 20px;
        background: linear-gradient(
            120deg,
            #111827 0%,
            #312e81 55%,
            #7c3aed 100%
        );
        color: white;
        margin-bottom: 1rem;
    }
    .hero h1 {
        margin: 0;
        font-size: 2.2rem;
    }
    .hero p {
        margin-top: .4rem;
        opacity: .9;
    }
    .manga-card {
        padding: 1rem;
        border: 1px solid rgba(128,128,128,.3);
        border-radius: 16px;
        margin-bottom: .8rem;
        display: flex;
        gap: 1rem;
        align-items: flex-start;
    }
    .manga-cover {
        width: 100px;
        height: 150px;
        object-fit: cover;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        flex-shrink: 0;
    }
    .manga-info {
        flex: 1;
    }
    .score {
        display: inline-block;
        padding: .25rem .6rem;
        border-radius: 999px;
        background: #7c3aed;
        color: white;
        font-size: .8rem;
        font-weight: bold;
    }
    .muted {
        opacity: .7;
        font-size: .9rem;
    }
    .admin-section {
        padding: 1rem;
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        margin-bottom: 1rem;
        background: #fafafa;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# NEO4J CONNECTION
# =========================================================
@st.cache_resource(show_spinner=False)
def create_driver(uri, username, password):
    driver = GraphDatabase.driver(
        uri,
        auth=(username, password)
    )
    driver.verify_connectivity()
    return driver


def get_connection():
    try:
        config = st.secrets["neo4j"]
        uri = config["uri"]
        username = config["username"]
        password = config["password"]
        database = config.get("database", "308b65ad")
        driver = create_driver(
            uri,
            username,
            password
        )
        return driver, database
    except Exception as e:
        st.error(
            "❌ เชื่อมต่อ Neo4j Aura ไม่สำเร็จ"
        )
        st.markdown(
            """
            ### ตรวจสอบ Streamlit Secrets
            ```toml
            [neo4j]
            uri = "neo4j+s://YOUR_INSTANCE.databases.neo4j.io"
            username = "neo4j"
            password = "YOUR_PASSWORD"
            database = "neo4j"
            ```
            """
        )
        st.warning(
            "ให้ใช้ URI / Username / Password / Database "
            "จาก Neo4j Aura จริง"
        )
        st.exception(e)
        st.stop()


driver, DATABASE = get_connection()

# =========================================================
# GENERAL QUERY FUNCTION
# =========================================================
def run_query(
    cypher,
    parameters=None,
    write=False
):
    if parameters is None:
        parameters = {}
    result = driver.execute_query(
        cypher,
        parameters_=parameters,
        database_=DATABASE,
        routing_=(
            RoutingControl.WRITE
            if write
            else RoutingControl.READ
        )
    )
    return [
        record.data()
        for record in result.records
    ]

# =========================================================
# CREATE CONSTRAINTS
# =========================================================
def create_constraints():
    run_query(
        """
        CREATE CONSTRAINT user_id_unique IF NOT EXISTS
        FOR (u:User)
        REQUIRE u.user_id IS UNIQUE
        """,
        write=True
    )
    run_query(
        """
        CREATE CONSTRAINT manga_id_unique IF NOT EXISTS
        FOR (m:Manga)
        REQUIRE m.manga_id IS UNIQUE
        """,
        write=True
    )

# =========================================================
# USER
# =========================================================
def get_users():
    return run_query(
        """
        MATCH (u:User)
        RETURN
            u.user_id AS user_id,
            u.name AS name
        ORDER BY
            u.user_id
        """
    )


def get_user(user_id):
    rows = run_query(
        """
        MATCH (
            u:User {
                user_id: $user_id
            }
        )
        RETURN
            u.user_id AS user_id,
            u.name AS name
        """,
        {
            "user_id": user_id
        }
    )
    return rows[0] if rows else None


# ==========================================
# [เพิ่มใหม่] ADMIN: เพิ่ม User
# ==========================================
def add_user(user_id, name):
    run_query(
        """
        MERGE (u:User {user_id: $user_id})
        SET u.name = $name
        """,
        {"user_id": user_id, "name": name},
        write=True
    )


# ==========================================
# [เพิ่มใหม่] ADMIN: แก้ไข User
# ==========================================
def update_user(user_id, new_name):
    run_query(
        """
        MATCH (u:User {user_id: $user_id})
        SET u.name = $new_name
        """,
        {"user_id": user_id, "new_name": new_name},
        write=True
    )


# ==========================================
# [เพิ่มใหม่] ADMIN: ลบ User
# ==========================================
def delete_user(user_id):
    run_query(
        """
        MATCH (u:User {user_id: $user_id})
        DETACH DELETE u
        """,
        {"user_id": user_id},
        write=True
    )

# =========================================================
# MANGA (แก้ไข: เพิ่ม image_url)
# =========================================================
def get_mangas():
    return run_query(
        """
        MATCH (m:Manga)
        RETURN
            m.manga_id AS manga_id,
            m.title AS title,
            m.image_url AS image_url
        ORDER BY
            m.title
        """
    )


# ==========================================
# [เพิ่มใหม่] ADMIN: เพิ่ม Manga
# ==========================================
def add_manga(manga_id, title, image_url=""):
    run_query(
        """
        MERGE (m:Manga {manga_id: $manga_id})
        SET m.title = $title, m.image_url = $image_url
        """,
        {"manga_id": manga_id, "title": title, "image_url": image_url},
        write=True
    )


# ==========================================
# [เพิ่มใหม่] ADMIN: แก้ไข Manga
# ==========================================
def update_manga(manga_id, new_title=None, new_image_url=None):
    set_clauses = []
    params = {"manga_id": manga_id}
    if new_title is not None:
        set_clauses.append("m.title = $new_title")
        params["new_title"] = new_title
    if new_image_url is not None:
        set_clauses.append("m.image_url = $new_image_url")
        params["new_image_url"] = new_image_url
    if set_clauses:
        run_query(
            f"MATCH (m:Manga {{manga_id: $manga_id}}) SET {', '.join(set_clauses)}",
            params,
            write=True
        )


# ==========================================
# [เพิ่มใหม่] ADMIN: ลบ Manga
# ==========================================
def delete_manga(manga_id):
    run_query(
        """
        MATCH (m:Manga {manga_id: $manga_id})
        DETACH DELETE m
        """,
        {"manga_id": manga_id},
        write=True
    )

# =========================================================
# LIKES
# =========================================================
def get_liked_mangas(user_id):
    return run_query(
        """
        MATCH
            (u:User {
                user_id: $user_id
            })
            -[:LIKES]->(m:Manga)
        RETURN
            m.manga_id AS manga_id,
            m.title AS title,
            m.image_url AS image_url
        ORDER BY
            title
        """,
        {
            "user_id": user_id
        }
    )


def add_like(
    user_id,
    manga_id
):
    run_query(
        """
        MATCH
            (u:User {
                user_id: $user_id
            }),
            (m:Manga {
                manga_id: $manga_id
            })
        MERGE
            (u)-[:LIKES]->(m)
        """,
        {
            "user_id": user_id,
            "manga_id": manga_id
        },
        write=True
    )


# ==========================================
# [เพิ่มใหม่] ADMIN: ลบ Like
# ==========================================
def delete_like(user_id, manga_id):
    run_query(
        """
        MATCH
            (u:User {user_id: $user_id})
            -[r:LIKES]->(m:Manga {manga_id: $manga_id})
        DELETE r
        """,
        {"user_id": user_id, "manga_id": manga_id},
        write=True
    )

# =========================================================
# RECOMMENDATION - SIMILAR USER
# =========================================================
def recommend_by_similar_user(
    user_id,
    limit=5
):
    return run_query(
        """
        MATCH
            (me:User {
                user_id: $user_id
            })
            -[:LIKES]->(liked:Manga)
            <-[:LIKES]-(similar:User)
            -[:LIKES]->(recommend:Manga)
        WHERE
            similar <> me
            AND NOT EXISTS {
                MATCH
                    (me)-[:LIKES]->(recommend)
            }
        WITH
            recommend,
            count(DISTINCT similar) AS score
        RETURN
            recommend.manga_id AS manga_id,
            recommend.title AS title,
            recommend.image_url AS image_url,
            score,
            "similar_user" AS type
        ORDER BY
            score DESC,
            title
        LIMIT $limit
        """,
        {
            "user_id": user_id,
            "limit": int(limit)
        }
    )

# =========================================================
# RECOMMENDATION - POPULAR
# =========================================================
def recommend_popular(
    limit=5
):
    return run_query(
        """
        MATCH (m:Manga)
        OPTIONAL MATCH
            (u:User)-[:LIKES]->(m)
        WITH
            m,
            count(u) AS score
        RETURN
            m.manga_id AS manga_id,
            m.title AS title,
            m.image_url AS image_url,
            score,
            "popular" AS type
        ORDER BY
            score DESC,
            title
        LIMIT $limit
        """,
        {
            "limit": int(limit)
        }
    )

# =========================================================
# MAIN RECOMMENDATION
# =========================================================
def get_recommendations(
    user_id,
    limit=5
):
    liked = get_liked_mangas(
        user_id
    )
    # User ใหม่
    if not liked:
        return (
            recommend_popular(limit),
            "new_user"
        )
    # Similar User
    rows = recommend_by_similar_user(
        user_id,
        limit
    )
    if rows:
        return (
            rows,
            "similar"
        )
    # Fallback
    return (
        recommend_popular(limit),
        "popular_fallback"
    )

# =========================================================
# CLEAR RECOMMENDS
# =========================================================
def clear_recommend_relationships(
    user_id=None
):
    if user_id:
        run_query(
            """
            MATCH
                (u:User {
                    user_id: $user_id
                })
                -[r:RECOMMENDS]->()
            DELETE r
            """,
            {
                "user_id": user_id
            },
            write=True
        )
    else:
        run_query(
            """
            MATCH
                ()-[r:RECOMMENDS]->()
            DELETE r
            """,
            write=True
        )

# =========================================================
# CREATE RECOMMENDS
# =========================================================
def create_recommend_relationships(
    user_id=None,
    limit=5
):
    if user_id:
        clear_recommend_relationships(
            user_id
        )
        target_users = [
            {
                "user_id": user_id
            }
        ]
    else:
        clear_recommend_relationships()
        target_users = get_users()
    created = 0
    for user in target_users:
        uid = user["user_id"]
        rows, mode = get_recommendations(
            uid,
            limit
        )
        for row in rows:
            run_query(
                """
                MATCH
                    (u:User {
                        user_id: $user_id
                    }),
                    (m:Manga {
                        manga_id: $manga_id
                    })
                MERGE
                    (u)-[r:RECOMMENDS]->(m)
                SET
                    r.score = $score,
                    r.type = $type
                """,
                {
                    "user_id": uid,
                    "manga_id": row["manga_id"],
                    "score": row["score"],
                    "type": row["type"]
                },
                write=True
            )
            created += 1
    return created

# =========================================================
# GET RECOMMENDS
# =========================================================
def get_recommends(
    user_id=None
):
    if user_id:
        return run_query(
            """
            MATCH
                (u:User {
                    user_id: $user_id
                })
                -[r:RECOMMENDS]->(m:Manga)
            RETURN
                u.user_id AS user_id,
                u.name AS user,
                m.manga_id AS manga_id,
                m.title AS title,
                m.image_url AS image_url,
                r.score AS score,
                r.type AS type
            ORDER BY
                score DESC,
                title
            """,
            {
                "user_id": user_id
            }
        )
    return run_query(
        """
        MATCH
            (u:User)
            -[r:RECOMMENDS]->(m:Manga)
        RETURN
            u.user_id AS user_id,
            u.name AS user,
            m.manga_id AS manga_id,
            m.title AS title,
            m.image_url AS image_url,
            r.score AS score,
            r.type AS type
        ORDER BY
            user_id,
            score DESC,
            title
        """
    )

# =========================================================
# SEARCH MANGA
# =========================================================
def search_manga(
    keyword=""
):
    return run_query(
        """
        MATCH (m:Manga)
        WHERE
            $keyword = ""
            OR
            toLower(m.title)
            CONTAINS
            toLower($keyword)
        OPTIONAL MATCH
            (u:User)-[:LIKES]->(m)
        RETURN
            m.manga_id AS manga_id,
            m.title AS title,
            m.image_url AS image_url,
            count(u) AS likes
        ORDER BY
            likes DESC,
            title
        """,
        {
            "keyword": keyword.strip()
        }
    )

# =========================================================
# GRAPH
# =========================================================
def get_graph(
    user_id=None
):
    if user_id:
        return run_query(
            """
            MATCH
                (u:User {
                    user_id: $user_id
                })
                -[r:LIKES|RECOMMENDS]->(m:Manga)
            RETURN
                u.user_id AS source_id,
                u.name AS source_name,
                type(r) AS relationship,
                m.manga_id AS target_id,
                m.title AS target_name
            """,
            {
                "user_id": user_id
            }
        )
    return run_query(
        """
        MATCH
            (u:User)
            -[r:LIKES|RECOMMENDS]->(m:Manga)
        RETURN
            u.user_id AS source_id,
            u.name AS source_name,
            type(r) AS relationship,
            m.manga_id AS target_id,
            m.title AS target_name
        LIMIT 100
        """
    )

# =========================================================
# DASHBOARD METRICS
# =========================================================
def get_metrics():
    users = run_query(
        """
        MATCH (u:User)
        RETURN count(u) AS count
        """
    )[0]["count"]
    mangas = run_query(
        """
        MATCH (m:Manga)
        RETURN count(m) AS count
        """
    )[0]["count"]
    likes = run_query(
        """
        MATCH ()-[r:LIKES]->()
        RETURN count(r) AS count
        """
    )[0]["count"]
    recommends = run_query(
        """
        MATCH ()-[r:RECOMMENDS]->()
        RETURN count(r) AS count
        """
    )[0]["count"]
    return (
        users,
        mangas,
        likes,
        recommends
    )

# =========================================================
# DEMO DATA (แก้ไข: เพิ่ม image_url)
# =========================================================
def create_demo_data():
    create_constraints()
    users = [
        {"user_id": "U001", "name": "Sompong"},
        {"user_id": "U002", "name": "Siriporn"},
        {"user_id": "U003", "name": "Niran"},
        {"user_id": "U004", "name": "Malee"},
        {"user_id": "U005", "name": "Chaiwat"},
        {"user_id": "U006", "name": "Kanya"},
        {"user_id": "U007", "name": "Anan"},
        {"user_id": "U008", "name": "Somying"},
        {"user_id": "U009", "name": "Prasit"},
        {"user_id": "U010", "name": "Nattaya"},
        {"user_id": "U011", "name": "New User"}
    ]
    mangas = [
        {"manga_id": "M001", "title": "Naruto", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/9/94/NarutoCoverTankobon1.jpg/220px-NarutoCoverTankobon1.jpg"},
        {"manga_id": "M002", "title": "One Piece", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/9/90/OnePieceCover1.jpg/220px-OnePieceCover1.jpg"},
        {"manga_id": "M003", "title": "Attack on Titan", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/d/d6/Shingeki_no_Kyojin_manga_volume_1.jpg/220px-Shingeki_no_Kyojin_manga_volume_1.jpg"},
        {"manga_id": "M004", "title": "Demon Slayer", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/4/46/Demon_Slayer_-_Kimetsu_no_Yaiba%2C_volume_1.jpg/220px-Demon_Slayer_-_Kimetsu_no_Yaiba%2C_volume_1.jpg"},
        {"manga_id": "M005", "title": "Death Note", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/6/6f/Death_Note_-_The_Kiss.jpg/220px-Death_Note_-_The_Kiss.jpg"},
        {"manga_id": "M006", "title": "My Hero Academia", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/0/03/My_Hero_Academia_volume_1.jpg/220px-My_Hero_Academia_volume_1.jpg"},
        {"manga_id": "M007", "title": "Jujutsu Kaisen", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/4/46/Jujutsu_Kaisen_volume_1_cover.jpg/220px-Jujutsu_Kaisen_volume_1_cover.jpg"},
        {"manga_id": "M008", "title": "Fullmetal Alchemist", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/0/0d/Fullmetal_Alchemist_manga_volume_1.jpg/220px-Fullmetal_Alchemist_manga_volume_1.jpg"},
        {"manga_id": "M009", "title": "Spy x Family", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/0/0b/Spy_x_Family_volume_1_cover.jpg/220px-Spy_x_Family_volume_1_cover.jpg"},
        {"manga_id": "M010", "title": "Chainsaw Man", "image_url": "https://upload.wikimedia.org/wikipedia/en/thumb/0/0d/Chainsaw_Man_volume_1_cover.jpg/220px-Chainsaw_Man_volume_1_cover.jpg"}
    ]
    likes = [
        ["U001", "M001"], ["U001", "M002"],
        ["U002", "M009"], ["U002", "M004"],
        ["U003", "M001"], ["U003", "M002"], ["U003", "M007"],
        ["U004", "M009"], ["U004", "M004"], ["U004", "M006"],
        ["U005", "M005"], ["U005", "M003"],
        ["U006", "M005"], ["U006", "M003"], ["U006", "M008"],
        ["U007", "M001"], ["U007", "M006"],
        ["U008", "M007"], ["U008", "M010"],
        ["U009", "M005"], ["U009", "M010"],
        ["U010", "M002"], ["U010", "M008"]
    ]
    run_query(
        """
        UNWIND $users AS row
        MERGE (u:User {user_id: row.user_id})
        SET u.name = row.name
        """,
        {"users": users},
        write=True
    )
    run_query(
        """
        UNWIND $mangas AS row
        MERGE (m:Manga {manga_id: row.manga_id})
        SET m.title = row.title, m.image_url = row.image_url
        """,
        {"mangas": mangas},
        write=True
    )
    run_query(
        """
        UNWIND $likes AS row
        MATCH
            (u:User {user_id: row[0]}),
            (m:Manga {manga_id: row[1]})
        MERGE (u)-[:LIKES]->(m)
        """,
        {"likes": likes},
        write=True
    )

# =========================================================
# [เพิ่มใหม่] HELPER: แสดง Manga Card พร้อมรูปภาพ
# =========================================================
DEFAULT_IMAGE = "https://via.placeholder.com/220x320/cccccc/666666?text=No+Image"


def display_manga_card(manga_id, title, image_url=None, score=None, rank=None, reason=None):
    img = image_url if image_url else DEFAULT_IMAGE
    score_html = f'<span class="score">#{rank} · score {score}</span>' if score is not None else ""
    reason_html = f'<p><b>เหตุผล:</b> {reason}</p>' if reason else ""
    st.markdown(
        f"""
        <div class="manga-card">
            <img src="{img}" class="manga-cover" onerror="this.src='{DEFAULT_IMAGE}'">
            <div class="manga-info">
                {score_html}
                <h3>{title}</h3>
                <div class="muted">Manga ID: {manga_id}</div>
                {reason_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# =========================================================
# SIDEBAR (แก้ไข: เพิ่ม Admin Panel)
# =========================================================
with st.sidebar:
    st.markdown(
        "## 📚 MangaGraph"
    )
    st.caption(
        "Neo4j Aura + Streamlit"
    )
    page = st.radio(
        "เมนู",
        [
            "Dashboard",
            "Recommendations",
            "Manga Search",
            "Manage Likes",
            "Graph Explorer",
            "Admin Panel"
        ]
    )
    st.divider()
    st.caption(
        "Manga Recommendation System"
    )

# =========================================================
# HEADER (แก้ไข: ลบ dedent() ออก)
# =========================================================
st.markdown(
    """
    <div class="hero">
        <h1>📚 Manga Recommendation System</h1>
        <p>ระบบแนะนำ Manga ด้วย Neo4j Graph Database</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# DASHBOARD
# =========================================================
if page == "Dashboard":
    st.subheader(
        "📊 ภาพรวมระบบ"
    )
    (
        users_count,
        manga_count,
        likes_count,
        recommends_count
    ) = get_metrics()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Users", users_count)
    c2.metric("Manga", manga_count)
    c3.metric("LIKES", likes_count)
    c4.metric("RECOMMENDS", recommends_count)
    st.divider()
    all_users = get_users()
    if all_users:
        options = {
            f"{u['user_id']} — {u['name']}": u["user_id"]
            for u in all_users
        }
        selected = st.selectbox(
            "เลือก User",
            list(options.keys())
        )
        user_id = options[selected]
        left, right = st.columns(2)
        with left:
            st.markdown("### ❤️ Manga ที่ User ชอบ")
            rows = get_liked_mangas(user_id)
            if rows:
                for row in rows:
                    display_manga_card(
                        row["manga_id"],
                        row["title"],
                        row.get("image_url")
                    )
            else:
                st.info("User นี้ยังไม่มี LIKES")
        with right:
            st.markdown("### ✨ Manga ที่ระบบแนะนำ")
            rows = get_recommends(user_id)
            if rows:
                for row in rows:
                    display_manga_card(
                        row["manga_id"],
                        row["title"],
                        row.get("image_url"),
                        score=row.get("score"),
                        reason=row.get("type")
                    )
            else:
                st.info("ยังไม่มี RECOMMENDS")

# =========================================================
# RECOMMENDATIONS
# =========================================================
elif page == "Recommendations":
    st.subheader(
        "✨ Manga Recommendation"
    )
    all_users = get_users()
    if not all_users:
        st.warning("ยังไม่มี User")
        st.stop()
    options = {
        f"{u['user_id']} — {u['name']}": u["user_id"]
        for u in all_users
    }
    selected = st.selectbox(
        "เลือก User",
        list(options.keys())
    )
    user_id = options[selected]
    limit = st.slider(
        "จำนวน Manga ที่แนะนำ",
        3,
        12,
        5
    )
    rows, mode = get_recommendations(
        user_id,
        limit
    )
    if mode == "similar":
        st.success(
            "👥 ระบบพบ User ที่มีความชอบคล้ายกัน "
            "จึงใช้ Similar User Recommendation"
        )
    elif mode == "new_user":
        st.info(
            "🆕 User นี้ยังไม่มี LIKES "
            "ระบบจึงใช้ Popular Manga Recommendation"
        )
    else:
        st.info(
            "ไม่พบ User ที่มีความชอบคล้ายกัน "
            "ระบบจึงใช้ Popular Manga เป็นทางเลือก"
        )
    if not rows:
        st.warning("ยังไม่มี Manga สำหรับแนะนำ")
    for i, row in enumerate(rows, start=1):
        if row["type"] == "similar_user":
            reason = "User ที่มีความชอบคล้ายกัน เคยชอบ Manga นี้"
        else:
            reason = "Manga นี้ได้รับความนิยม จากจำนวน LIKES"
        display_manga_card(
            row["manga_id"],
            row["title"],
            row.get("image_url"),
            score=row["score"],
            rank=i,
            reason=reason
        )
    st.divider()
    if st.button(
        "🔗 สร้างเส้น RECOMMENDS ให้ User นี้",
        type="primary",
        use_container_width=True
    ):
        count = create_recommend_relationships(
            user_id,
            limit
        )
        st.success(
            f"สร้าง RECOMMENDS สำเร็จ {count} เส้น"
        )
        st.rerun()

# =========================================================
# MANGA SEARCH
# =========================================================
elif page == "Manga Search":
    st.subheader(
        "🔎 ค้นหา Manga"
    )
    keyword = st.text_input(
        "ชื่อ Manga",
        placeholder="เช่น Naruto, One Piece, Jujutsu"
    )
    rows = search_manga(keyword)
    st.write(f"พบ {len(rows)} รายการ")
    if rows:
        for row in rows:
            display_manga_card(
                row["manga_id"],
                row["title"],
                row.get("image_url")
            )
            st.markdown(
                f'<div class="muted">จำนวน Likes: {row["likes"]}</div><br>',
                unsafe_allow_html=True
            )
    else:
        st.info("ไม่พบ Manga")

# =========================================================
# MANAGE LIKES
# =========================================================
elif page == "Manage Likes":
    st.subheader(
        "❤️ จัดการ Manga ที่ User ชอบ"
    )
    all_users = get_users()
    all_mangas = get_mangas()
    if not all_users:
        st.warning("ยังไม่มี User")
        st.stop()
    if not all_mangas:
        st.warning("ยังไม่มี Manga")
        st.stop()
    user_options = {
        f"{u['user_id']} — {u['name']}": u["user_id"]
        for u in all_users
    }
    selected_user = st.selectbox(
        "เลือก User",
        list(user_options.keys())
    )
    user_id = user_options[selected_user]
    st.markdown("### ❤️ Manga ที่ชอบอยู่แล้ว")
    liked = get_liked_mangas(user_id)
    if liked:
        for row in liked:
            col1, col2 = st.columns([4, 1])
            with col1:
                display_manga_card(
                    row["manga_id"],
                    row["title"],
                    row.get("image_url")
                )
            with col2:
                st.write("")
                st.write("")
                if st.button(
                    "❌ ลบ",
                    key=f"remove_{user_id}_{row['manga_id']}"
                ):
                    delete_like(user_id, row["manga_id"])
                    st.success("ลบ LIKES สำเร็จ")
                    st.rerun()
    else:
        st.info("User นี้ยังไม่มี LIKES")
    st.divider()
    manga_options = {
        f"{m['manga_id']} — {m['title']}": m["manga_id"]
        for m in all_mangas
    }
    selected_manga = st.selectbox(
        "เลือก Manga ที่ชอบ",
        list(manga_options.keys())
    )
    manga_id = manga_options[selected_manga]
    if st.button(
        "❤️ เพิ่ม LIKES",
        type="primary",
        use_container_width=True
    ):
        add_like(user_id, manga_id)
        st.success("เพิ่ม LIKES สำเร็จ")
        st.rerun()

# =========================================================
# GRAPH EXPLORER
# =========================================================
elif page == "Graph Explorer":
    st.subheader(
        "🕸️ Graph Explorer"
    )
    st.write(
        """
        แสดงความสัมพันธ์ระหว่าง User และ Manga
        - LIKES
        - RECOMMENDS
        """
    )
    all_users = get_users()
    if not all_users:
        st.warning("ยังไม่มี User")
        st.stop()
    options = {
        "ทั้งหมด": None
    }
    options.update({
        f"{u['user_id']} — {u['name']}": u["user_id"]
        for u in all_users
    })
    selected = st.selectbox(
        "เลือก User",
        list(options.keys())
    )
    user_id = options[selected]
    rows = get_graph(user_id)
    if not rows:
        st.info("ยังไม่มี Graph")
    else:
        dot = [
            "digraph G {",
            'rankdir="LR";',
            (
                'node [shape=box, '
                'style="rounded,filled", '
                'fillcolor="#f8fafc"];'
            )
        ]
        seen = set()
        for row in rows:
            source = row["source_id"]
            target = row["target_id"]
            relationship = row["relationship"]
            if source not in seen:
                safe_name = str(row["source_name"]).replace('"', "'")
                dot.append(
                    f'"{source}" [label="{safe_name}\\nUser"];'
                )
                seen.add(source)
            if target not in seen:
                safe_name = str(row["target_name"]).replace('"', "'")
                dot.append(
                    f'"{target}" [label="{safe_name}\\nManga"];'
                )
                seen.add(target)
            dot.append(
                f'"{source}" -> "{target}" [label="{relationship}"];'
            )
        dot.append("}")
        st.graphviz_chart(
            "\n".join(dot),
            use_container_width=True
        )
        st.markdown("### Relationship Data")
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )
    st.divider()
    st.markdown(
        "### Cypher สำหรับดู Graph ใน Neo4j"
    )
    st.code(
        """
MATCH p=(u:User)-[r:LIKES|RECOMMENDS]->(m:Manga)
RETURN p
LIMIT 100
""",
        language="cypher"
    )

# =========================================================
# [เพิ่มใหม่] ADMIN PANEL
# =========================================================
elif page == "Admin Panel":
    st.subheader("⚙️ Admin Panel - จัดการข้อมูลทั้งหมด")
    admin_tab = st.tabs([
        "👥 จัดการ Users",
        "📚 จัดการ Manga",
        "❤️ จัดการ Likes",
        "🔄 รีเซ็ตข้อมูล"
    ])

    # ========== USERS TAB ==========
    with admin_tab[0]:
        st.markdown('<div class="admin-section">', unsafe_allow_html=True)
        st.markdown("### ➕ เพิ่ม User ใหม่")
        col1, col2 = st.columns(2)
        with col1:
            new_user_id = st.text_input("User ID (เช่น U011)", key="new_uid")
        with col2:
            new_user_name = st.text_input("ชื่อ User", key="new_uname")
        if st.button("➕ เพิ่ม User", key="add_user_btn"):
            if new_user_id and new_user_name:
                try:
                    add_user(new_user_id, new_user_name)
                    st.success(f"เพิ่ม User '{new_user_name}' สำเร็จ")
                    st.rerun()
                except Exception as e:
                    st.error(f"เพิ่ม User ไม่สำเร็จ: {e}")
            else:
                st.warning("กรุณากรอกข้อมูลให้ครบ")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("#### 📋 รายชื่อ Users ทั้งหมด")
        all_users = get_users()
        if all_users:
            st.dataframe(
                pd.DataFrame(all_users),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("ยังไม่มี User")

        st.markdown("#### ✏️ แก้ไข / 🗑️ ลบ User")
        if all_users:
            selected_user = st.selectbox(
                "เลือก User",
                [f"{u['user_id']} — {u['name']}" for u in all_users],
                key="edit_user_sel"
            )
            sel_uid = selected_user.split(" — ")[0]
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input(
                    "แก้ไขชื่อ",
                    value=next(u["name"] for u in all_users if u["user_id"] == sel_uid),
                    key="edit_uname_val"
                )
                if st.button("💾 บันทึกชื่อ", key="save_uname"):
                    try:
                        update_user(sel_uid, new_name)
                        st.success("แก้ไขชื่อสำเร็จ")
                        st.rerun()
                    except Exception as e:
                        st.error(f"แก้ไขไม่สำเร็จ: {e}")
            with col2:
                st.write("")
                st.write("")
                if st.button("🗑️ ลบ User", key="del_user_btn", type="secondary"):
                    try:
                        delete_user(sel_uid)
                        st.success("ลบ User สำเร็จ (รวม LIKES และ RECOMMENDS)")
                        st.rerun()
                    except Exception as e:
                        st.error(f"ลบไม่สำเร็จ: {e}")

    # ========== MANGA TAB ==========
    with admin_tab[1]:
        st.markdown('<div class="admin-section">', unsafe_allow_html=True)
        st.markdown("### ➕ เพิ่ม Manga ใหม่")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_manga_id = st.text_input("Manga ID (เช่น M011)", key="new_mid")
        with col2:
            new_manga_title = st.text_input("ชื่อ Manga", key="new_mtitle")
        with col3:
            new_manga_img = st.text_input("URL รูปภาพ (ไม่บังคับ)", key="new_mimg")
        if st.button("➕ เพิ่ม Manga", key="add_manga_btn"):
            if new_manga_id and new_manga_title:
                try:
                    add_manga(new_manga_id, new_manga_title, new_manga_img)
                    st.success(f"เพิ่ม Manga '{new_manga_title}' สำเร็จ")
                    st.rerun()
                except Exception as e:
                    st.error(f"เพิ่ม Manga ไม่สำเร็จ: {e}")
            else:
                st.warning("กรุณากรอก Manga ID และชื่อ")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("#### 📋 รายชื่อ Manga ทั้งหมด")
        all_mangas = get_mangas()
        if all_mangas:
            st.dataframe(
                pd.DataFrame(all_mangas),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("ยังไม่มี Manga")

        st.markdown("#### ✏️ แก้ไข / 🗑️ ลบ Manga")
        if all_mangas:
            selected_manga = st.selectbox(
                "เลือก Manga",
                [f"{m['manga_id']} — {m['title']}" for m in all_mangas],
                key="edit_manga_sel"
            )
            sel_mid = selected_manga.split(" — ")[0]
            sel_manga = next(m for m in all_mangas if m["manga_id"] == sel_mid)
            col1, col2, col3 = st.columns(3)
            with col1:
                new_title = st.text_input(
                    "แก้ไขชื่อ",
                    value=sel_manga.get("title", ""),
                    key="edit_mtitle_val"
                )
                if st.button("💾 บันทึกชื่อ", key="save_mtitle"):
                    try:
                        update_manga(sel_mid, new_title=new_title)
                        st.success("แก้ไขชื่อสำเร็จ")
                        st.rerun()
                    except Exception as e:
                        st.error(f"แก้ไขไม่สำเร็จ: {e}")
            with col2:
                new_img = st.text_input(
                    "URL รูปภาพใหม่",
                    value=sel_manga.get("image_url") or "",
                    key="edit_mimg_val"
                )
                if st.button("💾 บันทึกรูป", key="save_mimg"):
                    try:
                        update_manga(sel_mid, new_image_url=new_img)
                        st.success("บันทึกรูปสำเร็จ")
                        st.rerun()
                    except Exception as e:
                        st.error(f"บันทึกไม่สำเร็จ: {e}")
            with col3:
                st.write("")
                st.write("")
                if st.button("🗑️ ลบ Manga", key="del_manga_btn", type="secondary"):
                    try:
                        delete_manga(sel_mid)
                        st.success("ลบ Manga สำเร็จ (รวม LIKES และ RECOMMENDS)")
                        st.rerun()
                    except Exception as e:
                        st.error(f"ลบไม่สำเร็จ: {e}")

    # ========== LIKES TAB ==========
    with admin_tab[2]:
        st.markdown('<div class="admin-section">', unsafe_allow_html=True)
        st.markdown("### ➕ เพิ่ม Like ใหม่")
        all_users = get_users()
        all_mangas = get_mangas()
        if not all_users or not all_mangas:
            st.warning("ยังไม่มี User หรือ Manga")
        else:
            col1, col2 = st.columns(2)
            with col1:
                like_user = st.selectbox(
                    "User",
                    [f"{u['user_id']} — {u['name']}" for u in all_users],
                    key="like_user_sel"
                )
            with col2:
                like_manga = st.selectbox(
                    "Manga",
                    [f"{m['manga_id']} — {m['title']}" for m in all_mangas],
                    key="like_manga_sel"
                )
            if st.button("➕ เพิ่ม Like", key="add_like_btn"):
                uid = like_user.split(" — ")[0]
                mid = like_manga.split(" — ")[0]
                try:
                    add_like(uid, mid)
                    st.success("เพิ่ม Like สำเร็จ")
                    st.rerun()
                except Exception as e:
                    st.error(f"เพิ่ม Like ไม่สำเร็จ: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("####  รายชื่อ Likes ทั้งหมด")
        all_users_for_likes = get_users()
        likes_data = []
        for u in all_users_for_likes:
            liked = get_liked_mangas(u["user_id"])
            for row in liked:
                likes_data.append({
                    "User ID": u["user_id"],
                    "User Name": u["name"],
                    "Manga ID": row["manga_id"],
                    "Manga Title": row["title"]
                })
        if likes_data:
            st.dataframe(
                pd.DataFrame(likes_data),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("ยังไม่มี Likes")

        st.markdown("#### 🗑️ ลบ Like")
        if likes_data:
            like_options = [
                f"{l['User ID']} ({l['User Name']}) → {l['Manga ID']} ({l['Manga Title']})"
                for l in likes_data
            ]
            selected_like = st.selectbox(
                "เลือก Like ที่ต้องการลบ",
                like_options,
                key="del_like_sel"
            )
            idx = like_options.index(selected_like)
            target = likes_data[idx]
            if st.button("️ ลบ Like ที่เลือก", key="del_like_btn", type="secondary"):
                try:
                    delete_like(target["User ID"], target["Manga ID"])
                    st.success("ลบ Like สำเร็จ")
                    st.rerun()
                except Exception as e:
                    st.error(f"ลบไม่สำเร็จ: {e}")

    # ========== RESET TAB ==========
    with admin_tab[3]:
        st.markdown("### 🔄 รีเซ็ตข้อมูล")
        st.warning(
            "⚠️ การรีเซ็ตจะลบข้อมูลทั้งหมดใน Neo4j "
            "(Users, Manga, Likes, Recommends)"
        )
        if st.button("🗑️ ลบข้อมูลทั้งหมด", type="primary"):
            try:
                run_query("MATCH (n) DETACH DELETE n", write=True)
                st.success("ลบข้อมูลทั้งหมดสำเร็จ")
                st.rerun()
            except Exception as e:
                st.error(f"ลบไม่สำเร็จ: {e}")
        st.divider()
        st.markdown("### 📦 สร้างข้อมูลตัวอย่าง")
        st.caption(
            "สร้าง User + Manga + LIKES\n"
            "U011 จะไม่มี LIKES เพื่อใช้ทดสอบ Cold Start"
        )
        if st.button(
            "📦 สร้าง User + Manga + LIKES",
            type="primary",
            use_container_width=True
        ):
            try:
                create_demo_data()
                st.success("สร้างข้อมูลตัวอย่างสำเร็จ")
                st.rerun()
            except Exception as e:
                st.error(f"สร้างไม่สำเร็จ: {e}")