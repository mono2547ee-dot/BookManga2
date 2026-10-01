from __future__ import annotations

from typing import Any

import streamlit as st
from neo4j import GraphDatabase, RoutingControl


# =========================================================
# NEO4J CONFIG
# =========================================================

def _config() -> tuple[str, str, str, str]:
    cfg = st.secrets["neo4j"]

    return (
        cfg["uri"],
        cfg["username"],
        cfg["password"],
        cfg.get("database", "neo4j"),
    )


# =========================================================
# DRIVER
# =========================================================

@st.cache_resource(show_spinner=False)
def get_driver():
    """
    สร้าง Neo4j Driver
    """

    uri, username, password, _ = _config()

    driver = GraphDatabase.driver(
        uri,
        auth=(username, password)
    )

    driver.verify_connectivity()

    return driver


# =========================================================
# QUERY
# =========================================================

def query(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    *,
    write: bool = False
) -> list[dict[str, Any]]:
    """
    Execute Cypher Query

    write=False
        อ่านข้อมูล

    write=True
        เพิ่ม / แก้ไข / ลบข้อมูล
    """

    _, _, _, database = _config()

    records, _, _ = get_driver().execute_query(
        cypher,
        parameters_=parameters or {},
        database_=database,
        routing_=(
            RoutingControl.WRITE
            if write
            else RoutingControl.READ
        ),
    )

    return [
        record.data()
        for record in records
    ]


# =========================================================
# PING
# =========================================================

def ping() -> bool:
    """
    ตรวจสอบการเชื่อมต่อ Neo4j
    """

    rows = query(
        "RETURN 1 AS ok"
    )

    return bool(
        rows
        and rows[0]["ok"] == 1
    )


# =========================================================
# CREATE SCHEMA
# =========================================================

def create_schema() -> None:
    """
    สร้าง Constraint สำหรับ User และ Manga
    """

    statements = [

        """
        CREATE CONSTRAINT user_id_unique IF NOT EXISTS
        FOR (u:User)
        REQUIRE u.user_id IS UNIQUE
        """,

        """
        CREATE CONSTRAINT manga_id_unique IF NOT EXISTS
        FOR (m:Manga)
        REQUIRE m.manga_id IS UNIQUE
        """
    ]

    for statement in statements:

        query(
            statement,
            write=True
        )


# =========================================================
# DEMO DATA
# =========================================================

def seed_demo_data() -> None:
    """
    สร้างข้อมูลตัวอย่าง Manga Recommendation

    User:
        U001 - U011

    Manga:
        M001 - M010

    U011 เป็น New User
    และไม่มี LIKES
    """

    create_schema()

    # =====================================================
    # USERS
    # =====================================================

    users = [

        {
            "user_id": "U001",
            "name": "Sompong"
        },

        {
            "user_id": "U002",
            "name": "Siriporn"
        },

        {
            "user_id": "U003",
            "name": "Niran"
        },

        {
            "user_id": "U004",
            "name": "Malee"
        },

        {
            "user_id": "U005",
            "name": "Chaiwat"
        },

        {
            "user_id": "U006",
            "name": "Kanya"
        },

        {
            "user_id": "U007",
            "name": "Anan"
        },

        {
            "user_id": "U008",
            "name": "Somying"
        },

        {
            "user_id": "U009",
            "name": "Prasit"
        },

        {
            "user_id": "U010",
            "name": "Nattaya"
        },

        {
            "user_id": "U011",
            "name": "New User"
        }
    ]


    # =====================================================
    # MANGA
    # =====================================================

    mangas = [

        {
            "manga_id": "M001",
            "title": "Naruto"
        },

        {
            "manga_id": "M002",
            "title": "One Piece"
        },

        {
            "manga_id": "M003",
            "title": "Attack on Titan"
        },

        {
            "manga_id": "M004",
            "title": "Demon Slayer"
        },

        {
            "manga_id": "M005",
            "title": "Death Note"
        },

        {
            "manga_id": "M006",
            "title": "My Hero Academia"
        },

        {
            "manga_id": "M007",
            "title": "Jujutsu Kaisen"
        },

        {
            "manga_id": "M008",
            "title": "Fullmetal Alchemist"
        },

        {
            "manga_id": "M009",
            "title": "Spy x Family"
        },

        {
            "manga_id": "M010",
            "title": "Chainsaw Man"
        }
    ]


    # =====================================================
    # LIKES
    # =====================================================

    likes = [

        ["U001", "M001"],
        ["U001", "M002"],

        ["U002", "M009"],
        ["U002", "M004"],

        ["U003", "M001"],
        ["U003", "M002"],
        ["U003", "M007"],

        ["U004", "M009"],
        ["U004", "M004"],
        ["U004", "M006"],

        ["U005", "M005"],
        ["U005", "M003"],

        ["U006", "M005"],
        ["U006", "M003"],
        ["U006", "M008"],

        ["U007", "M001"],
        ["U007", "M006"],

        ["U008", "M007"],
        ["U008", "M010"],

        ["U009", "M005"],
        ["U009", "M010"],

        ["U010", "M002"],
        ["U010", "M008"]
    ]


    # =====================================================
    # CREATE USERS
    # =====================================================

    query(
        """
        UNWIND $rows AS row

        MERGE (
            u:User {
                user_id: row.user_id
            }
        )

        SET
            u.name = row.name
        """,

        {
            "rows": users
        },

        write=True
    )


    # =====================================================
    # CREATE MANGA
    # =====================================================

    query(
        """
        UNWIND $rows AS row

        MERGE (
            m:Manga {
                manga_id: row.manga_id
            }
        )

        SET
            m.title = row.title
        """,

        {
            "rows": mangas
        },

        write=True
    )


    # =====================================================
    # CREATE LIKES
    # =====================================================

    query(
        """
        UNWIND $rows AS row

        MATCH
            (u:User {
                user_id: row[0]
            }),

            (m:Manga {
                manga_id: row[1]
            })

        MERGE
            (u)-[:LIKES]->(m)
        """,

        {
            "rows": likes
        },

        write=True
    )


# =========================================================
# USERS
# =========================================================

def get_users() -> list[dict[str, Any]]:

    return query(
        """
        MATCH (u:User)

        RETURN
            u.user_id AS user_id,
            u.name AS name

        ORDER BY
            u.user_id
        """
    )


def get_user(
    user_id: str
) -> dict[str, Any] | None:

    rows = query(
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


# =========================================================
# MANGA
# =========================================================

def get_mangas() -> list[dict[str, Any]]:

    return query(
        """
        MATCH (m:Manga)

        RETURN
            m.manga_id AS manga_id,
            m.title AS title

        ORDER BY
            m.title
        """
    )


# =========================================================
# LIKES
# =========================================================

def get_liked_mangas(
    user_id: str
) -> list[dict[str, Any]]:

    return query(
        """
        MATCH
            (u:User {
                user_id: $user_id
            })
            -[:LIKES]->(m:Manga)

        RETURN
            m.manga_id AS manga_id,
            m.title AS title

        ORDER BY
            title
        """,

        {
            "user_id": user_id
        }
    )


def add_like(
    user_id: str,
    manga_id: str
) -> None:

    query(
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


# =========================================================
# SIMILAR USER RECOMMENDATION
# =========================================================

def recommend_by_similar_user(
    user_id: str,
    limit: int = 5
) -> list[dict[str, Any]]:

    return query(
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
# POPULAR RECOMMENDATION
# =========================================================

def recommend_popular(
    limit: int = 5
) -> list[dict[str, Any]]:

    return query(
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
    user_id: str,
    limit: int = 5
) -> tuple[list[dict[str, Any]], str]:

    liked = get_liked_mangas(
        user_id
    )

    # =====================================================
    # NEW USER
    # =====================================================

    if not liked:

        return (
            recommend_popular(limit),
            "new_user"
        )


    # =====================================================
    # SIMILAR USER
    # =====================================================

    rows = recommend_by_similar_user(
        user_id,
        limit
    )

    if rows:

        return (
            rows,
            "similar"
        )


    # =====================================================
    # FALLBACK POPULAR
    # =====================================================

    return (
        recommend_popular(limit),
        "popular_fallback"
    )


# =========================================================
# RECOMMENDS
# =========================================================

def clear_recommend_relationships(
    user_id: str | None = None
) -> None:

    if user_id:

        query(
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

        query(
            """
            MATCH
                ()-[r:RECOMMENDS]->()

            DELETE r
            """,

            write=True
        )


def create_recommend_relationships(
    user_id: str | None = None,
    limit: int = 5
) -> int:

    # =====================================================
    # TARGET USERS
    # =====================================================

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


    # =====================================================
    # CREATE RECOMMENDS
    # =====================================================

    for user in target_users:

        uid = user["user_id"]

        rows, mode = get_recommendations(
            uid,
            limit
        )

        for row in rows:

            query(
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
    user_id: str | None = None
) -> list[dict[str, Any]]:

    if user_id:

        return query(
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


    return query(
        """
        MATCH
            (u:User)
            -[r:RECOMMENDS]->(m:Manga)

        RETURN
            u.user_id AS user_id,
            u.name AS user,

            m.manga_id AS manga_id,
            m.title AS title,

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
    keyword: str = ""
) -> list[dict[str, Any]]:

    return query(
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

def graph_neighborhood(
    user_id: str | None = None,
    limit: int = 100
) -> list[dict[str, Any]]:

    if user_id:

        return query(
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

            LIMIT $limit
            """,

            {
                "user_id": user_id,
                "limit": int(limit)
            }
        )


    return query(
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

        LIMIT $limit
        """,

        {
            "limit": int(limit)
        }
    )


# =========================================================
# DASHBOARD METRICS
# =========================================================

def get_dashboard_metrics() -> dict[str, int]:

    users = query(
        """
        MATCH (u:User)

        RETURN count(u) AS count
        """
    )[0]["count"]


    mangas = query(
        """
        MATCH (m:Manga)

        RETURN count(m) AS count
        """
    )[0]["count"]


    likes = query(
        """
        MATCH ()-[r:LIKES]->()

        RETURN count(r) AS count
        """
    )[0]["count"]


    recommends = query(
        """
        MATCH ()-[r:RECOMMENDS]->()

        RETURN count(r) AS count
        """
    )[0]["count"]


    return {
        "users": users,
        "mangas": mangas,
        "likes": likes,
        "recommends": recommends
    }